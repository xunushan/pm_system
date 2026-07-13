"""E2E S8 触发：多阶段目标 -> 完成第1阶段 -> 级联 emit phase_completed -> 衔接卡。

链路（全真实，经 API/Service + 事件总线 dispatcher 自动推卡）：
  1. POST /drafts 写多阶段规划（1 主题 × 2 阶段 × 2 任务）
  2. PlanAppSvc.confirm 落库（4 表）
  3. ScheduleAppSvc.activate 激活第1阶段
  4. PATCH /tasks/{id} complete 完成第1阶段全部任务（即时级联）
  5. cascade emit phase_completed -> dispatcher 自动调 on_phase_completed
     -> find_next_phase 查到第2阶段 -> build_phase_linking_card -> send_card
  6. 用户在飞书点「确认激活」(btn_activate) 或「暂不激活」(btn_defer)

纪律：数据经真实 API + Service 方法，不直改 DB、不 mock。推卡由 supervisor
事件驱动自动触发（非直调推卡），测 emit->dispatcher->handler 全链路。
"""

import httpx
from sqlalchemy import select

from app.config import settings
from app.db.session import SessionLocal
from app.models.phase import Phase
from app.models.task import Task
from app.services.plan_app_svc import PlanAppSvc
from app.services.schedule_app_svc import ScheduleAppSvc

API = "http://localhost:8001"
CHAT_ID = settings.feishu_default_chat_id

# 1 主题 × 2 阶段 × 2 任务（多阶段才能触发衔接）
PLAN_CONTENT = {
    "goal": {
        "name": "S8衔接测试目标",
        "description": "多阶段目标，测阶段完成衔接卡",
        "time_range_start": "2026-07-13",
        "time_range_end": "2026-08-31",
        "scheduled_start_date": "2026-07-13",
    },
    "themes": [
        {
            "name": "S8测试专题",
            "type": "learning",
            "description": "多阶段衔接",
            "phases": [
                {
                    "name": "S8-P1：基础",
                    "sort_order": 1,
                    "tasks": [
                        {"name": "P1-任务A", "sort_order": 1, "description": "基础A"},
                        {"name": "P1-任务B", "sort_order": 2, "description": "基础B"},
                    ],
                },
                {
                    "name": "S8-P2：进阶",
                    "sort_order": 2,
                    "tasks": [
                        {"name": "P2-任务A", "sort_order": 1, "description": "进阶A"},
                        {"name": "P2-任务B", "sort_order": 2, "description": "进阶B"},
                    ],
                },
            ],
        }
    ],
}


def main() -> None:
    # 1. 真实 API 写 draft
    resp = httpx.post(
        f"{API}/api/v1/drafts",
        json={"user_id": "feishu_user", "story_type": "plan", "content": PLAN_CONTENT},
        timeout=10,
    )
    resp.raise_for_status()
    draft_id = resp.json()["data"]["draft_id"]
    print(f"[1] draft 写入 (真实 API): {draft_id}")

    # 2. 确认方案落库（直调 Service，对齐 S1 webhook 确认后的落库动作）
    with SessionLocal() as db:
        data = PlanAppSvc(db).confirm(draft_id)
        print(
            f"[2] 方案确认落库: goal={data.goal_name} themes={data.themes_created} "
            f"phases={data.phases_created} tasks={data.tasks_created}"
        )

    # 3. 激活第1阶段（sort_order=1）
    with SessionLocal() as db:
        p1 = db.scalars(select(Phase).where(Phase.name == "S8-P1：基础")).one()
        from datetime import date, timedelta

        deadline = date.today() + timedelta(days=7)
        ScheduleAppSvc(db).activate(p1.id, deadline, user_id="feishu_user")
        p1_id = p1.id
        print(f"[3] 第1阶段已激活: {p1.id[:8]} deadline={deadline}")

    # 4. 完成第1阶段全部任务（PATCH /tasks/{id}/complete，即时级联）
    with SessionLocal() as db:
        p1 = db.get(Phase, p1_id)
        tasks = db.scalars(
            select(Task).where(Task.phase_id == p1_id).order_by(Task.sort_order)
        ).all()
        for t in tasks:
            r = httpx.post(
                f"{API}/api/v1/tasks/{t.id}/complete",
                json={"user_id": "feishu_user"},
                timeout=10,
            )
            r.raise_for_status()
            print(f"[4] 任务完成: {t.name} -> {t.id[:8]}")

    # 5. 级联 emit phase_completed -> dispatcher 自动推衔接卡（异步，等几秒）
    print("\n[5] 等待 dispatcher 推衔接卡（phase_completed 事件异步分发）...")
    print("    衔接卡含第2阶段 + 建议 deadline + 确认激活/暂不激活按钮")
    print("\n>>> 请在飞书「🎯 阶段衔接」卡上：")
    print("    1. 选 deadline + 点「确认激活」（应立即变绿 + 激活第2阶段）")
    print("    2. 或点「暂不激活」（应立即变橙 + 记暂缓）")


if __name__ == "__main__":
    main()
