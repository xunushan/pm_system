"""E2E S3 重测：候选列全部待执行任务（9个），带 phase_info 区分同名。

目的：让用户能勾选不同任务，验证「勾选的」与「刷新后显示的」是否一致。
"""

import httpx
from sqlalchemy import text

from app.config import settings
from app.db.session import SessionLocal
from app.services.daily_app_svc import DailyAppSvc

API = "http://localhost:8001"
CHAT_ID = settings.feishu_default_chat_id
_DATE = "2026-07-13"
PREREQ_NAME = "环境准备：确认 Obsidian 仓库可写"


def main() -> None:
    # 真实 API 取候选池
    resp = httpx.get(f"{API}/api/v1/daily/plans/pool", params={"user_id": "feishu_user"}, timeout=10)
    resp.raise_for_status()
    pool = resp.json()["data"]
    pending = pool["pending_tasks"]
    print(f"[pool] {len(pending)} 个待执行任务（候选全列）")

    # 候选列全部待执行任务，带 phase_info 区分同名
    candidate_tasks = [
        {
            "task_id": t["task_id"],
            "name": t["name"],
            "executor": "human",  # learning -> human
            "phase_info": f"{t['phase_name']}",
        }
        for t in pending
    ]
    print("[候选]:")
    for c in candidate_tasks:
        print(f"  - {c['name']}（{c['phase_info']}）")

    prereq_id = "pre-env-prepare-0001"
    prerequisites = [{"subtask_id": prereq_id, "name": PREREQ_NAME}]

    with SessionLocal() as db:
        message_id = DailyAppSvc(db).push_daily_plan_card(
            date_str=_DATE,
            candidate_tasks=candidate_tasks,
            prerequisites=prerequisites,
            chat_id=CHAT_ID,
        )
    if not message_id:
        raise SystemExit("[FAIL] send_card 未返回 message_id")
    print(f"\n[OK] 今日计划卡已推（9 候选 + phase_info）: message_id = {message_id}")
    print("\n>>> 请在飞书勾选你想要的任意任务（可勾不同阶段的不同任务）+ 点「确认今日计划」")
    print(">>> 我会核对：你勾选的 task_id vs DB 落库的 task_id 是否一致")
    print(f"\n>>> message_id={message_id}")


if __name__ == "__main__":
    main()
