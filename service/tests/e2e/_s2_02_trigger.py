"""E2E S2-02 触发：名额超限（第 4 个激活应被拒 1004）。

前置：S2-01 已激活 3 个 phase（active_count=3，MAX=3）。
推只含「知识管理闭环」（未激活）的调度卡，用户勾选+确认 -> 3+1>3 -> QuotaExceeded 1004。
走服务：直调 ScheduleAppSvc.push_schedule_card（推卡逻辑在 Service）。
"""

from sqlalchemy import text

from app.config import settings
from app.db.session import SessionLocal
from app.services.schedule_app_svc import ScheduleAppSvc

CHAT_ID = settings.feishu_default_chat_id


def main() -> None:
    with SessionLocal() as db:
        goal = db.execute(
            text("SELECT id, name FROM goals WHERE name='知识库构建' LIMIT 1")
        ).fetchone()
        goal_id, goal_name = goal[0], goal[1]
        # 只取未激活的「知识管理闭环」专题
        row = db.execute(
            text(
                "SELECT id, name, type FROM themes WHERE goal_id=:gid AND status='未开始' LIMIT 1"
            ),
            {"gid": goal_id},
        ).fetchone()
        if not row:
            raise SystemExit("[FAIL] 无未激活专题（S2-01 未留名额？）")
        themes = [{"theme_id": row[0], "name": row[1], "type": row[2], "goal_id": goal_id}]

    print(f"[超限测试] 当前 active=3, 激活「{row[1]}」(1个) -> 3+1>3 应 1004")
    with SessionLocal() as db:
        message_id = ScheduleAppSvc(db).push_schedule_card(
            goal_name=goal_name, themes=themes, chat_id=CHAT_ID, h5_url=settings.h5_base_url
        )
    if not message_id:
        raise SystemExit("[FAIL] send_card 未返回 message_id")
    print(f"[OK] 调度卡 A（仅知识管理闭环）已推: message_id = {message_id}")
    print("\n>>> 请在飞书卡片上：勾选「知识管理闭环」-> 下一步 -> 填 deadline -> 确认调度")
    print(">>> 预期：webhook 返回 1004，卡片不刷新（已知：超限未兜底 update_card），DB 不变")
    print(f"\n>>> message_id={message_id}")


if __name__ == "__main__":
    main()
