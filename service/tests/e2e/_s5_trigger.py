"""E2E S5 trigger：经真实 API generate_summary -> 直调 push_daily_summary_card。

走服务：GET /daily/summary/generate（只读统计）-> push_daily_summary_card（推日终卡）。
测：webhook confirm_btn card_type=daily_summary（checker 切换任务状态 + 确认日终）+ write_daily_md。
"""

import httpx

from app.config import settings
from app.db.session import SessionLocal
from app.services.daily_app_svc import DailyAppSvc

API = "http://localhost:8001"
CHAT_ID = settings.feishu_default_chat_id


def main() -> None:
    # 1. 真实 API 取日终统计
    resp = httpx.get(
        f"{API}/api/v1/daily/summary/generate",
        params={"user_id": "feishu_user", "date": "2026-07-13"},
        timeout=10,
    )
    resp.raise_for_status()
    s = resp.json()["data"]
    daily_id = s["daily_id"]
    print(f"[daily] id={daily_id[:8]}... date={s['date']} is_confirmed={s['is_confirmed']}")
    print(
        f"[统计] completed={len(s['completed_tasks'])} "
        f"incomplete={len(s['incomplete_tasks'])} "
        f"phase_health={len(s['phase_health'])}"
    )
    for t in s["completed_tasks"]:
        print(f"  ✅ {t['name']} | {t.get('theme_name', '')}")
    for t in s["incomplete_tasks"]:
        print(f"  ❌ {t['name']} | {t.get('theme_name', '')}")

    # 2. 直调 Service 推日终总结卡
    completed = [
        {"task_id": t["task_id"], "name": t["name"], "theme_name": t.get("theme_name", "")}
        for t in s["completed_tasks"]
    ]
    incomplete = [
        {"task_id": t["task_id"], "name": t["name"], "theme_name": t.get("theme_name", "")}
        for t in s["incomplete_tasks"]
    ]
    phase_health = [
        {
            "phase_id": p["phase_id"],
            "name": p["name"],
            "completed": p["completed"],
            "total": p["total"],
            "rate": p["rate"],
            "status": p["status"],
        }
        for p in s["phase_health"]
    ]
    with SessionLocal() as db:
        message_id = DailyAppSvc(db).push_daily_summary_card(
            daily_id=daily_id,
            date_str=s["date"],
            completed_tasks=completed,
            incomplete_tasks=incomplete,
            phase_health=phase_health,
            chat_id=CHAT_ID,
        )
    if not message_id:
        raise SystemExit("[FAIL] send_card 未返回 message_id")
    print(f"\n[OK] 日终总结卡已推: message_id = {message_id}")
    print(f"[card_registry] type=daily_summary, daily_id={daily_id[:8]}...")
    print("\n>>> 请在飞书日终总结卡上：")
    print("    1. 勾选/取消 checker 切换任务完成状态（应立即反转，方案B）")
    print("    2. 点「确认日终总结」（应立即变绿 + daily.md 生成）")
    print(f"\n>>> daily_id={daily_id}\n>>> message_id={message_id}")


if __name__ == "__main__":
    main()
