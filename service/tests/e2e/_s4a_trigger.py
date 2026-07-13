"""E2E S4A trigger：调真实 callback API record_output 触发验收卡。

走服务：POST /api/callback/opencode/output（opencode 产出回调本走此入口）。
构造产出文件（模拟 opencode 执行产出），触发：
  record_output -> INSERT workspace_progress -> 异步推验收卡（build_verification_card）
  + set_card_context({type:verification, task_id})
然后测 btn_pass/btn_reject 真实点击。

后续补：真实 opencode dispatch（造 dev 任务 + start_agent_serve + 等执行）。
"""

import os
import sys

import httpx
from sqlalchemy import text

from app.config import settings

API = "http://localhost:8001"

# S4A-02 用：指定第二个 task（脚本参数传 task_id，不传则取第一个待执行）
TARGET_TASK_ID = sys.argv[1] if len(sys.argv) > 1 else None


def main() -> None:
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        if TARGET_TASK_ID:
            row = db.execute(
                text(
                    "SELECT t.id, t.name, w.id, w.path FROM tasks t "
                    "JOIN phases p ON t.phase_id=p.id JOIN themes th ON p.theme_id=th.id "
                    "JOIN workspaces w ON th.id=w.theme_id WHERE t.id=:tid"
                ),
                {"tid": TARGET_TASK_ID},
            ).fetchone()
        else:
            row = db.execute(
                text(
                    "SELECT t.id, t.name, w.id, w.path FROM tasks t "
                    "JOIN phases p ON t.phase_id=p.id JOIN themes th ON p.theme_id=th.id "
                    "JOIN workspaces w ON th.id=w.theme_id WHERE t.status='待执行' LIMIT 1"
                )
            ).fetchone()
        task_id, task_name, workspace_id, ws_path = row[0], row[1], row[2], row[3]

    print(f"[task] {task_name} ({task_id[:8]}...)")
    print(f"[workspace] {workspace_id[:8]}... path={ws_path}")

    # 造产出文件（模拟 opencode 执行产出）
    os.makedirs(ws_path, exist_ok=True)
    output_file = os.path.join(ws_path, "e2e_s4a_output.md")
    with open(output_file, "w") as f:
        f.write(f"# {task_name} 产出\n\n这是 e2e S4A 测试产出文件（模拟 opencode 执行）。\n")
    print(f"[产出文件] {output_file}")

    # 调真实 callback API
    resp = httpx.post(
        f"{API}/api/callback/opencode/output",
        json={
            "task_id": task_id,
            "workspace_id": workspace_id,
            "outputs": [{"file_path": output_file, "file_type": "note", "summary": "e2e测试产出"}],
        },
        timeout=30,
    )
    print(f"\n[callback API] {resp.status_code} -> {resp.json()}")
    resp.raise_for_status()
    print("\n>>> 验收卡已推（含产出文件 + 验收通过/需要修改按钮）")
    print(">>> 请在飞书验收卡上点「验收通过」测 btn_pass（应立即变绿）")
    print(f">>> task_id={task_id}")


if __name__ == "__main__":
    main()
