"""OpenCode 客户端：对接真实 opencode serve 1.17.16 API（方案 B：全局单进程 + 多 session）。

P0 修复（2026-07-09 端到端验证）：原实现 3 缺陷已修正——
  1. 真正用 subprocess 启动全局 opencode serve 子进程（幂等，类级单例 _proc）
  2. 端点改为真实 API：POST /session、POST /session/{id}/message、GET /session
  3. 协议改为 session + message 模型（建会话 + 同步发消息拿结果）

方案 B 设计：
  - 全局一个 opencode serve 进程（固定端口 opencode_serve_port），服务所有 workspace
  - 每个 workspace 用独立 session（POST /session {"directory": workspace 路径}）
  - session_id 存 agent_processes.session_id，复用避免重复建会话
  - dispatch_task：POST /session/{id}/message 同步返回完整 assistant message
  - health：GET /session（真端点）
  - shutdown：标记 agent_processes stopped（全局进程保留，服务其他 workspace）

opencode client 是 app/clients/，纯 IO，不含业务逻辑。
事务内禁止 IO/HTTP（铁律 §3#3）：本 client 由 AppSvc 事务提交后异步调用，
内部 DB 操作（agent_processes）是独立短事务，不与 AppSvc 事务混用。
"""

import logging
import subprocess
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.exceptions import InternalError
from app.core.times import now_utc_naive
from app.db.session import SessionLocal
from app.models.agent_process import AgentProcess
from app.models.phase import Phase
from app.models.task import Task
from app.models.theme import Theme
from app.models.workspace import Workspace

logger = logging.getLogger(__name__)


class OpenCodeClient:
    """对接真实 opencode serve 的客户端（方案 B：全局单进程 + 多 session）。

    事务外异步调用（铁律 §3#3：事务内禁止 IO/HTTP）。
    DB 操作用传入 session 或自建 SessionLocal（async 场景）。
    """

    # 类级单例：全局 opencode serve 子进程（所有实例共享，幂等启动）
    _proc: subprocess.Popen | None = None

    def __init__(self, db: Session | None = None) -> None:
        self.db = db

    @property
    def base_url(self) -> str:
        """全局 opencode serve 基址（由 serve_port 派生）。"""
        return f"http://127.0.0.1:{settings.opencode_serve_port}"

    # ---- 全局 serve 进程管理 ----

    def start_serve(self) -> None:
        """启动全局 opencode serve 子进程（幂等）。

        方案 B：所有 workspace 共享一个 serve 进程。
        若已在运行（_proc.poll() is None）则直接返回。
        """
        if OpenCodeClient._proc is not None and OpenCodeClient._proc.poll() is None:
            return  # 已运行
        port = settings.opencode_serve_port
        OpenCodeClient._proc = subprocess.Popen(
            ["opencode", "serve", "--port", str(port), "--hostname", "127.0.0.1"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._wait_port(port, timeout=15)
        logger.info("start_serve: port=%d pid=%d", port, OpenCodeClient._proc.pid)

    @staticmethod
    def _wait_port(port: int, timeout: float = 15) -> None:
        """轮询 GET /session 直到 200（serve 就绪）。

        区分异常（P1-2）：
          - ConnectError：服务还没起来，继续轮询（正常启动流程）
          - HTTPStatusError / 其他：服务起来了但报错，立即抛出（避免吞掉 500）

        Args:
            port: opencode serve 端口。
            timeout: 最大等待秒数。

        Raises:
            InternalError: 超时未就绪 / 服务起来了但 HTTP 报错。
        """
        deadline = time.monotonic() + timeout
        url = f"http://127.0.0.1:{port}/session"
        while time.monotonic() < deadline:
            try:
                if httpx.get(url, timeout=2).status_code == 200:
                    return
            except httpx.ConnectError:
                pass  # 还没起来，继续轮询
            except httpx.HTTPStatusError as exc:
                raise InternalError(
                    f"opencode serve 启动异常（{exc.response.status_code}）"
                ) from exc
            time.sleep(0.5)
        raise InternalError(f"opencode serve 启动超时（端口 {port} 未就绪）")

    # ---- session 管理 ----

    def _ensure_session(self, workspace_id: str) -> str | None:
        """为 workspace 建/复用 opencode session（directory=workspace 路径）。

        铁律 §3#3（事务内禁止 IO/HTTP）：HTTP 调用在事务外。
        逻辑（事务内查 -> 事务外 HTTP -> 事务内回填）：
          1. 事务内：查 agent_processes，已有 session_id 则直接复用（无需 HTTP）
          2. 事务内：无 session_id 则查 workspace.path，建/更新 agent_processes 占位记录
             （session_id=None），commit
          3. 事务外：POST /session {"directory": <绝对路径>} -> session_id
          4. 事务内：回填 agent_processes.session_id，commit

        Args:
            workspace_id: 工作空间 ID。

        Returns:
            session id，或 None（workspace 不存在 / HTTP 失败已记录日志）。
        """
        # ---- 事务1：查/建占位记录（session_id=None），拿 workspace 路径 ----
        own_session = self.db is None
        db = self.db or SessionLocal()
        try:
            ap = db.scalar(select(AgentProcess).where(AgentProcess.workspace_id == workspace_id))
            # 复用已有 session_id（无需 HTTP）
            if ap and ap.session_id:
                return ap.session_id

            ws = db.get(Workspace, workspace_id)
            if ws is None:
                logger.warning("_ensure_session: workspace 不存在 %s", workspace_id)
                return None
            directory = str(Path(ws.path).resolve())

            now = now_utc_naive()
            if ap:
                ap.session_id = None  # 占位，待 HTTP 后回填
                ap.status = "running"
                ap.port = settings.opencode_serve_port
                ap.last_heartbeat = now
            else:
                db.add(
                    AgentProcess(
                        id=str(uuid4()),
                        workspace_id=workspace_id,
                        port=settings.opencode_serve_port,
                        status="running",
                        session_id=None,  # 占位
                        last_heartbeat=now,
                    )
                )
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("_ensure_session 事务1 失败: ws=%s", workspace_id)
            return None
        finally:
            if own_session:
                db.close()

        # ---- 事务外：POST /session 建会话（IO/HTTP，铁律 §3#3）----
        try:
            resp = httpx.post(
                f"{self.base_url}/session",
                json={"directory": directory},
                timeout=30,
            )
            resp.raise_for_status()
            session_id = resp.json()["id"]
        except Exception:
            logger.exception("_ensure_session HTTP 建会话失败: ws=%s", workspace_id)
            return None

        # ---- 事务2：回填 session_id（纯 DB，无 IO）----
        db2 = SessionLocal() if own_session else self.db  # noqa: PLW2901
        try:
            ap2 = db2.scalar(select(AgentProcess).where(AgentProcess.workspace_id == workspace_id))
            if ap2:
                ap2.session_id = session_id
                db2.commit()
            logger.info("_ensure_session: 新建 session ws=%s sid=%s", workspace_id, session_id)
            return session_id
        except Exception:
            db2.rollback()
            logger.exception("_ensure_session 事务2 回填失败: ws=%s", workspace_id)
            return session_id  # session 已建，回填失败不丢失 session_id
        finally:
            if own_session:
                db2.close()

    def _get_workspace_id_for_subtask(self, sub: dict[str, Any]) -> str | None:
        """从 subtask.task_id 反查 workspace_id（task -> phase -> theme -> workspace）。"""
        task_id = sub.get("task_id")
        if not task_id:
            return None
        own_session = self.db is None
        db = self.db or SessionLocal()
        try:
            row = db.execute(
                select(Workspace.id)
                .join(Theme, Workspace.theme_id == Theme.id)
                .join(Phase, Phase.theme_id == Theme.id)
                .join(Task, Task.phase_id == Phase.id)
                .where(Task.id == task_id)
            ).first()
            return row[0] if row else None
        finally:
            if own_session:
                db.close()

    # ---- 启动 / 任务下发 ----

    def start_agent_serve(self, workspace_id: str, task: dict[str, Any] | None = None) -> int:
        """启动全局 serve（幂等）+ 确保 session + 下发首任务（如有）。

        方案 B：全局单进程，start_serve 幂等；_ensure_session 建/复用 session。

        Args:
            workspace_id: 工作空间 ID。
            task: 触发启动的智能体任务（含 task_id/name/phase_id）。

        Returns:
            serve 端口（>0 成功），-1 失败。
        """
        try:
            self.start_serve()
            session_id = self._ensure_session(workspace_id)
            if session_id is None:
                logger.warning("start_agent_serve: 无法确保 session ws=%s", workspace_id)
                return -1
        except Exception:
            logger.exception("start_agent_serve 失败: ws=%s", workspace_id)
            return -1

        # 事务后：下发首个任务（HTTP POST，事务外 IO）
        # dispatch_task 失败不影响已提交的 agent_processes 记录（由 health/重试处理）
        if task:
            try:
                self.dispatch_task(workspace_id, task)
            except Exception:
                logger.exception("start_agent_serve dispatch 首任务失败: ws=%s", workspace_id)

        return settings.opencode_serve_port

    def dispatch_task(
        self, workspace_id: str, task: dict[str, Any], port: int | None = None
    ) -> dict[str, Any]:
        """下发任务：POST /session/{id}/message，同步拿结果。

        真实 opencode serve API：POST /session/{id}/message 同步返回完整 assistant message，
        结果在 parts[].text（type=="text"），info.finish=="stop" 表示完成。

        Args:
            workspace_id: 工作空间 ID。
            task: 任务载荷（含 task_id/name/phase_id 等）。prompt 取 name 或 prompt 字段。
            port: 忽略（方案 B 全局单端口，保留签名兼容旧调用方 _retry_dispatch）。

        Returns:
            {"finish": str, "result": str, "tokens": dict}。
        """
        session_id = self._ensure_session(workspace_id)
        if session_id is None:
            raise InternalError(f"无可用 session: ws={workspace_id}")
        prompt = task.get("name") or task.get("prompt") or str(task)
        resp = httpx.post(
            f"{self.base_url}/session/{session_id}/message",
            json={"parts": [{"type": "text", "text": prompt}]},
            timeout=300,  # agent 执行可能久
        )
        resp.raise_for_status()
        msg = resp.json()
        # P1-1：合并所有 text part（多段输出不截断）
        result = "".join(p["text"] for p in msg.get("parts", []) if p.get("type") == "text")
        info = msg.get("info", {})
        logger.info(
            "dispatch_task: ws=%s task=%s finish=%s",
            workspace_id,
            task.get("task_id"),
            info.get("finish"),
        )
        return {"finish": info.get("finish"), "result": result, "tokens": info.get("tokens")}

    def dispatch_pre_subtasks(self, subtasks: list[dict[str, Any]]) -> None:
        """异步执行前置子任务（session + message，统一通道）。

        方案 B：逐个反查 workspace -> ensure session -> POST /session/{id}/message。
        事务后异步调用（由 daily_app_svc.trigger_async 触发）。失败非阻塞（逐个 try）。

        Args:
            subtasks: 前置子任务列表，每项含 id/name/task_id 等。
        """
        self._dispatch_subtasks(subtasks, label="pre")

    def dispatch_post_subtasks(self, subtasks: list[dict[str, Any]]) -> None:
        """异步执行后置子任务（session + message，统一通道）。

        方案 B：与 dispatch_pre_subtasks 同通道（POST /session/{id}/message）。
        事务后异步调用（由 task_app_svc.trigger_post_async 触发，Story4B）。失败非阻塞。

        Args:
            subtasks: 后置子任务列表，每项含 id/name/task_id 等。
        """
        self._dispatch_subtasks(subtasks, label="post")

    def _dispatch_subtasks(self, subtasks: list[dict[str, Any]], label: str) -> None:
        """逐个下发子任务（session + message）的公共实现。"""
        for sub in subtasks:
            try:
                ws_id = self._get_workspace_id_for_subtask(sub)
                if not ws_id:
                    logger.warning(
                        "dispatch_%s_subtasks: 无法定位 workspace: %s", label, sub.get("id")
                    )
                    continue
                self.start_serve()
                session_id = self._ensure_session(ws_id)
                if not session_id:
                    continue
                resp = httpx.post(
                    f"{self.base_url}/session/{session_id}/message",
                    json={"parts": [{"type": "text", "text": sub.get("name", "")}]},
                    timeout=300,
                )
                resp.raise_for_status()
                logger.info("dispatch_%s_subtasks: sub=%s done", label, sub.get("id"))
            except Exception:
                logger.exception("dispatch_%s_subtasks 失败: %s", label, sub.get("id"))

    # ---- 健康检查 / 关闭 ----

    def health(self, workspace_id: str) -> bool:
        """健康检查 opencode serve（GET /session 真端点）。

        Args:
            workspace_id: 工作空间 ID（方案 B 全局进程，workspace 参数保留兼容）。

        Returns:
            True 如果 serve 响应 200，False 如果不可达。
        """
        try:
            return httpx.get(f"{self.base_url}/session", timeout=5).status_code == 200
        except Exception:
            logger.warning("health 检查失败: ws=%s", workspace_id)
            return False

    def shutdown(self, workspace_id: str) -> bool:
        """停止该 workspace 的 agent 会话（标记 agent_processes stopped）。

        方案 B：全局 serve 进程保留（服务其他 workspace），仅标记该 workspace 的
        agent_process 为 stopped。下次 start_agent_serve 会重新 ensure session。
        铁律 §3#3：纯 DB 写 + commit，无 IO/HTTP。

        Returns:
            True 如果成功标记 stopped，False 如果无 running 进程。
        """
        own_session = self.db is None
        db = self.db or SessionLocal()
        try:
            ap = db.scalar(
                select(AgentProcess).where(
                    AgentProcess.workspace_id == workspace_id,
                    AgentProcess.status == "running",
                )
            )
            if ap is None:
                return False
            ap.status = "stopped"
            db.commit()
            logger.info("shutdown: ws=%s stopped（全局 serve 进程保留）", workspace_id)
            return True
        except Exception:
            db.rollback()
            logger.exception("shutdown DB 更新失败: ws=%s", workspace_id)
            return False
        finally:
            if own_session:
                db.close()

    def delete_session(self, workspace_id: str) -> bool:
        """退掉该 workspace 的 opencode session（DELETE /session/:sessionID）。

        方案 B（D26）：3 次不通过时退该 task 的 session，全局 serve 进程保留
        （服务其他 workspace）。用户可用 session_id 在本地接管，"/pm 确认完成"
        后系统重新建/复用 session 驱动后续任务（doc/06 Story4A 步骤8）。

        铁律 §3#3（事务内禁止 IO/HTTP）：事务1 纯 DB 写（清 session_id + 标 stopped）
        -> 事务外 HTTP DELETE。DB 先于 HTTP 清理，无事务2。

        DB 先清的原因（P1 修复）：无论 HTTP 成败，DB session_id 均已 None，
        下次 _ensure_session 必走重建路径（不会复用旧 session_id 导致 404 阻断）。
        HTTP 失败时 opencode session 变孤儿，serve 进程退出自然清理（可接受）。

        签名取 workspace_id（与 shutdown 一致）：调用方（3 次重试逻辑）持 workspace_id，
        内部查 agent_processes 拿 session_id 再 DELETE，避免调用方再查一次 DB。

        失败非阻塞：HTTP DELETE 失败记日志返回 False，不抛（DB 已 None，下次重建）。
        不调 shutdown_serve（全局 serve 保留）。

        Args:
            workspace_id: 工作空间 ID。

        Returns:
            True 如果 HTTP DELETE 成功，False 如果无 session/无记录/HTTP 失败。
        """
        # ---- 事务1：查 session_id + 清 DB（纯 DB 写，无 IO）----
        # DB 先清：session_id=None + status=stopped，commit 后再 HTTP。
        # 无论 HTTP 成败，DB 均已 None，下次 _ensure_session 必重建（无 404 阻断）。
        own_session = self.db is None
        db = self.db or SessionLocal()
        try:
            ap = db.scalar(select(AgentProcess).where(AgentProcess.workspace_id == workspace_id))
            if ap is None or ap.session_id is None:
                logger.info("delete_session: 无 session 可退 ws=%s", workspace_id)
                return False
            session_id = ap.session_id
            ap.session_id = None
            ap.status = "stopped"
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("delete_session 事务1 DB 清理失败: ws=%s", workspace_id)
            return False
        finally:
            if own_session:
                db.close()

        # ---- 事务外：DELETE /session/{id} 退 session（IO/HTTP，铁律 §3#3）----
        # 无事务2：DB 已在事务1清完。HTTP 失败返回 False，DB 保持 None（下次重建）。
        try:
            resp = httpx.delete(f"{self.base_url}/session/{session_id}", timeout=30)
            resp.raise_for_status()
        except Exception:
            logger.exception(
                "delete_session HTTP 退 session 失败: ws=%s sid=%s（DB 已清，下次重建）",
                workspace_id,
                session_id,
            )
            return False

        logger.info(
            "delete_session: 已退 session ws=%s sid=%s（全局 serve 保留）",
            workspace_id,
            session_id,
        )
        return True

    @classmethod
    def shutdown_serve(cls) -> None:
        """关闭全局 opencode serve 子进程（应用退出时调用，P1-3）。

        方案 B：全局单进程，在 FastAPI lifespan shutdown 时 terminate，
        避免 uvicorn --reload 重载遗留僵尸进程。
        """
        proc = cls._proc
        if proc is None:
            return
        if proc.poll() is None:  # 仍在运行
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            logger.info("shutdown_serve: opencode serve 已终止 pid=%d", proc.pid)
        cls._proc = None
