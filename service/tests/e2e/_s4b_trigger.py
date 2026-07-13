"""E2E S4B trigger：人完成任务 -> 推后置确认卡。

走服务：
  1. 真实 API PATCH /tasks/{id} 标记完成（即时级联，人执行路径）
  2. 直调 TaskAppSvc.push_post_confirm_card 推后置确认卡（兜底，Skill 缺位）

测：confirm_btn card_type=post_confirm + story4B_全选/全不选 真实点击。
"""

import sys

import httpx
from sqlalchemy import text

from app.config import settings
from app.db.session import SessionLocal
from app.services.task_app_svc import TaskAppSvc

API = "http://localhost:8001"
CHAT_ID = settings.feishu_default_chat_id
TASK_ID = sys.argv[1] if len(sys.argv) > 1 else "c4daa182-41dd-4229-be15-63c00fdb0015"

# 模拟 pm-subtask Skill 生成的后置清单（后置基于模板 + 工作空间快照，LLM 生成）
POST_SUBTASKS = [
    {"id": "post-1", "name": "更新 README 文档"},
    {"id": "post-2", "name": "提交代码到 Git"},
    {"id": "post-3", "name": "更新面试题库"},
]


def main() -> None:
    # 1. 真实 API 标记完成（人执行路径，即时级联）
    with SessionLocal() as db:
        row = db.execute(
            text("SELECT name, status FROM tasks WHERE id=:tid"), {"tid": TASK_ID}
        ).fetchone()
        if not row:
            raise SystemExit(f"[FAIL] task 不存在: {TASK_ID}")
        task_name = row[0]
        print(f"[task] {task_name} ({TASK_ID[:8]}...) status={row[1]}")

    if row[1] != "已完成":
        resp = httpx.patch(
            f"{API}/api/v1/tasks/{TASK_ID}",
            json={"status": "已完成", "triggered_by": "user"},
            timeout=10,
        )
        print(f"[PATCH 完成] {resp.status_code} -> {resp.json().get('data', {})}")
        resp.raise_for_status()

    # 2. 直调 Service 推后置确认卡
    with SessionLocal() as db:
        message_id = TaskAppSvc(db).push_post_confirm_card(
            task_id=TASK_ID,
            task_name=task_name,
            post_subtasks=POST_SUBTASKS,
            chat_id=CHAT_ID,
        )
    if not message_id:
        raise SystemExit("[FAIL] send_card 未返回 message_id")
    print(f"\n[OK] 后置确认卡已推: message_id = {message_id}")
    print(f"[card_registry] type=post_confirm, task_id={TASK_ID[:8]}... post_subtasks=3")
    print("\n>>> 请在飞书后置确认卡上：")
    print("    1. 可点「全选」/「全不选」测 toggle（应立即刷新 checker 状态）")
    print("    2. 勾选后置 + 点「确认」（应立即变绿色已确认）")
    print(f"\n>>> message_id={message_id}")


if __name__ == "__main__":
    main()
