# P0 修复方案：opencode.py 重写（对接真实 opencode serve 1.17.16）

> 2026-07-09 端到端验证发现 S4A `app/clients/opencode.py` 架构缺陷。本文档基于**真实实测** opencode serve 1.17.16 API，给出修复方案。

## 一、真实 opencode serve API（实测确认）

实测 `opencode serve --port 18100`（v1.17.16）暴露的 HTTP API：

### 1. 建会话
```
POST /session  {"directory": "<workspace绝对路径>"}
-> 200 {"id":"ses_...", "directory":"...", "version":"1.17.16", "slug":"...", ...}
```

### 2. 发任务（同步返回结果！）
```
POST /session/{id}/message  {"parts":[{"type":"text","text":"任务描述"}]}
-> 200 {
  "info": {
    "role":"assistant", "agent":"build", "finish":"stop",
    "modelID":"astron-code-latest", "providerID":"xfyun",
    "tokens":{...}, "time":{"created":...,"completed":...},
    "id":"msg_...", "sessionID":"ses_..."
  },
  "parts": [
    {"type":"step-start", ...},
    {"type":"text","text":"<执行结果>"},        // <- 结果
    {"type":"step-finish","reason":"stop", ...}
  ]
}
```
实测：发 `{"parts":[{"type":"text","text":"回复一个字:好"}]}` -> 同步返回 `parts[1].text="好"`，`finish="stop"`。

### 3. 实时进度（可选，SSE）
```
GET /event  -> text/event-stream
data: {"id":"evt_...","type":"server.connected|message.updated|tool.called|...", "properties":{...}}
```

### 4. 查会话
```
GET /session        -> 200 [{id, directory, tokens, ...}]   (JSON)
GET /session/{id}   -> 会话详情
```

### 假端点（S4A 误用，实测全是 SPA fallback）
`/task` `/run` `/health` `/shutdown` -> 全返回 `200 text/html`（index.html），**非 API**。

---

## 二、S4A 实现的偏差（3 条，均有证据）

1. **无 subprocess 启动 opencode serve 进程**：`start_agent_serve` 只在 DB 写端口记录，没有 `subprocess.Popen(["opencode","serve",...])`。dispatch 往无人监听端口发请求。
2. **端点全假**：`/task` `/run` `/health` `/shutdown` 实测全是 SPA fallback（返回 index.html）。
3. **协议模型错**：假设"POST /task 同步拿 JSON"的简单 RPC；真实是 **session + message 模型**（POST /session 建会话 + POST /session/{id}/message 发任务，同步返回结果）。

---

## 三、修复方案对比

### 方案 A：贴合 doc/03 §五（每 workspace 一进程）
- 每个 workspace 起 `opencode serve --port {动态端口}` 子进程，记 PID
- 该进程建 session（directory=workspace）
- dispatch: POST /session/{id}/message
- health: GET /session（真端点）；shutdown: terminate PID
- ✅ 贴合 doc/03 设计（进程隔离/心跳/端口管理/关机恢复）
- ❌ 多进程管理复杂，资源占用高（每 workspace 一进程）

### 方案 B：简化（全局单进程 + 多 session）★ 推荐
- 起一个全局 opencode serve（固定端口，subprocess）
- 每个 workspace 用不同 session（POST /session {"directory": workspace}）
- dispatch: POST /session/{id}/message 同步拿结果
- health: GET /session；shutdown: 进程级 terminate
- ✅ 简单，一进程服务所有 workspace，资源省
- ✅ 同步 message 拿结果，无需复杂 SSE 客户端
- ❌ 偏离 doc/03"每 workspace 一进程"（需记录决策，同步更新 doc/03 §五）

### 方案 C：纯 CLI（opencode run 子进程，不用 serve）
- 每任务 subprocess 跑 `opencode run "任务" --cwd workspace`，拿 stdout
- ✅ 最简单，无 serve 进程管理
- ❌ 完全偏离 doc/03"主 Agent 进程长驻"（失去进程复用/心跳/端口），每任务冷启动慢

---

## 四、推荐：方案 B

**理由**：
1. 真实 opencode serve **一个进程天然支持多 session**（POST /session 指定不同 directory），方案 A 的"每 workspace 一进程"是过度设计。
2. 方案 B 保留 doc/03 核心意图（opencode serve 长驻 + workspace 隔离 + 心跳），仅简化"每 workspace 一进程"为"全局一进程多 session"。
3. 真实 API 支持**同步 message 拿结果**（`POST /session/{id}/message` 同步返回完整 assistant message），无需复杂 SSE 客户端。SSE `/event` 仅在需要实时进度（流式/tool 调用）时订阅，可选。
4. opencode 已配 provider（xfyun/astron-code），能真实执行任务。

---

## 五、opencode.py 重写骨架（方案 B）

```python
import subprocess
import time
import httpx
from app.config import settings

class OpenCodeClient:
    def __init__(self, db=None):
        self.base_url = settings.opencode_base_url  # http://localhost:{serve_port}
        self._proc: subprocess.Popen | None = None  # 全局 serve 进程

    def start_serve(self, port: int) -> None:
        """启动全局 opencode serve 子进程（首次下发时，幂等）。"""
        if self._proc and self._proc.poll() is None:
            return  # 已运行
        self._proc = subprocess.Popen(
            ["opencode", "serve", "--port", str(port), "--hostname", "127.0.0.1"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        self._wait_port(port, timeout=10)

    def _wait_port(self, port, timeout=10):
        # 轮询 GET /session 直到 200
        ...

    def _ensure_session(self, workspace_id: str) -> str:
        """为 workspace 建会话（directory=workspace 路径），复用 agent_processes.session_id。"""
        # 查 agent_processes 是否已有 session_id -> 复用
        # 无则 POST /session {"directory": workspace.path} -> session_id，存 agent_processes
        ...

    def dispatch_task(self, workspace_id: str, task: dict) -> dict:
        """下发任务：POST /session/{id}/message，同步拿结果。"""
        self.start_serve(settings.serve_port)  # 幂等启动
        session_id = self._ensure_session(workspace_id)
        resp = httpx.post(
            f"{self.base_url}/session/{session_id}/message",
            json={"parts": [{"type": "text", "text": task["prompt"]}]},
            timeout=300,  # agent 执行可能久
        )
        resp.raise_for_status()
        msg = resp.json()
        result = next((p["text"] for p in msg["parts"] if p.get("type") == "text"), "")
        return {"finish": msg["info"]["finish"], "result": result, "tokens": msg["info"]["tokens"]}

    def health(self, workspace_id: str) -> bool:
        """健康检查：GET /session（真端点，200 JSON）。"""
        try:
            return httpx.get(f"{self.base_url}/session", timeout=5).status_code == 200
        except Exception:
            return False

    def shutdown(self, workspace_id: str) -> bool:
        """停止：标记 agent_processes stopped。全局 serve 进程保留（服务其他 workspace）。"""
        # 全局进程不 terminate（多 workspace 共享）；仅标记该 workspace 的 agent_process stopped
        ...
```

---

## 六、需同步改动

1. **`app/clients/opencode.py`**：按骨架重写（subprocess + session + message）
2. **`app/models/agent_process.py`**：加 `session_id` 列（存 opencode session id，复用避免重复建会话）+ migration
3. **`app/config.py`**：加 `serve_port`（全局 opencode serve 端口，如 18800）；`opencode_base_url` 指向该端口
4. **`doc/03 §五`**（只读，记录决策到 PROGRESS.md / 07_决策文档）：全局单进程 + 多 session 替代"每 workspace 一进程"
5. **dispatch_pre_subtasks / dispatch_post_subtasks**：统一改用 session+message（或保留为 opencode run CLI，二选一，推荐统一用 message）

---

## 七、测试策略

- **单测**：mock httpx（POST /session /message 响应），验证 dispatch_task 解析结果正确、finish 判断、session 复用
- **集成**：起真实 opencode serve（fixture，端口 18800），发真实 message（xfyun provider，小任务如"回复一个字"），拿结果验证端到端
- **回归**：S4A 现有 6 个 timeout 测试（test_opencode_client.py）需适配新 API
