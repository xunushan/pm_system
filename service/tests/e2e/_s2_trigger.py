"""E2E S2 触发：直调 ScheduleAppSvc.push_schedule_card 推调度卡片 A（选专题）。

走服务（铁律 §11：推卡逻辑在 Service，Skill 只识别意图调 Service；
e2e 测服务直调 Service 推卡方法）。
S2 流程：推卡片 A -> 用户勾选专题+点「下一步」-> patch 卡片 B（填 deadline）->
用户填 deadline+点「确认调度」-> 激活 phase + 级联 + workspace 初始化。

S2-01：勾选 2 个专题激活（留名额给 S2-02 超限验证，名额 ≤3）。
"""

from sqlalchemy import text

from app.config import settings
from app.db.session import SessionLocal
from app.services.schedule_app_svc import ScheduleAppSvc

CHAT_ID = settings.feishu_default_chat_id
H5_URL = settings.h5_base_url


def main() -> None:
    # 从 S1 产出动态取 goal + themes（不硬编码）
    with SessionLocal() as db:
        goal = db.execute(
            text("SELECT id, name FROM goals WHERE name='知识库构建' LIMIT 1")
        ).fetchone()
        if not goal:
            raise SystemExit("[FAIL] 无 goal，先跑 S1")
        goal_id, goal_name = goal[0], goal[1]
        rows = db.execute(
            text("SELECT id, name, type FROM themes WHERE goal_id=:gid ORDER BY rowid"),
            {"gid": goal_id},
        ).fetchall()
        themes = []
        for i, r in enumerate(rows):
            item = {"theme_id": r[0], "name": r[1], "type": r[2]}
            if i == 0:
                item["goal_id"] = goal_id  # 首项带 goal_id（存映射用，builder 不渲染）
            themes.append(item)

    print(f"[goal] {goal_name} ({goal_id})")
    print(f"[themes] {len(themes)} 个专题:")
    for t in themes:
        print(f"  - {t['name']} ({t['theme_id'][:8]}...) type={t['type']}")

    with SessionLocal() as db:
        message_id = ScheduleAppSvc(db).push_schedule_card(
            goal_name=goal_name, themes=themes, chat_id=CHAT_ID, h5_url=H5_URL
        )
    if not message_id:
        raise SystemExit("[FAIL] send_card 未返回 message_id")
    print(f"\n[OK] 调度卡片 A 已推送: message_id = {message_id}")
    print(f"[card_registry] type=schedule_a, goal_id={goal_id}")
    print("\n>>> 请在飞书卡片 A 上：")
    print("    1. 勾选「知识获取」+「知识沉淀」2 个专题（留名额给 S2-02）")
    print("    2. 点「下一步」-> 卡片 patch 成 B（填 deadline）")
    print("    3. 卡片 B 填 2 个 deadline（如 2026-07-20 / 2026-07-25）")
    print("    4. 点「确认调度」")
    print(f"\n>>> goal_id={goal_id}")
    print(f">>> message_id={message_id}")


if __name__ == "__main__":
    main()
