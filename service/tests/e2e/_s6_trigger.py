"""E2E S6 trigger：直调 Service push_weekly_summary_card_from_db 推周总结卡。

走服务（铁律 §11 推卡全归 Service）：Week=2026-W29 ->
  push_weekly_summary_card_from_db 内部「日汇总到周」：
    StatsAppSvc.get_weekly_stats 取本周完成任务列表/每日趋势/阶段健康度/智能体产出
    -> 组装 -> build_weekly_summary_card -> FeishuClient.send_card -> 存映射。
不 mock 数据、不查 DB 拼（pm-summary Skill 未来也只调本方法，传 week + chat_id）。

测：webhook action_id=story6_已阅周总结（确认已阅 + write_weekly_md）。
"""

from app.config import settings
from app.db.session import SessionLocal
from app.services.weekly_app_svc import WeeklyAppSvc

CHAT_ID = settings.feishu_default_chat_id
WEEK = "2026-W29"


def main() -> None:
    with SessionLocal() as db:
        message_id = WeeklyAppSvc(db).push_weekly_summary_card_from_db(
            week=WEEK,
            chat_id=CHAT_ID,
            # next_week_advice 是 pm-summary LLM 生成（铁律 §3#1），
            # 服务推卡/定时触发无 LLM 建议，传空串（卡片该行留空）。
            next_week_advice="",
        )
    if not message_id:
        raise SystemExit("[FAIL] send_card 未返回 message_id")
    print(f"[OK] 周总结卡已推（服务自汇总日->周，无 mock）: message_id = {message_id}")
    print(f"[card_registry] type=weekly_summary, week={WEEK}")
    print("\n>>> 请在飞书周总结卡上点「已阅」（应立即变绿 + weekly.md 生成）")


if __name__ == "__main__":
    main()
