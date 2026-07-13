"""E2E S3 触发：直调 DailyAppSvc.push_daily_plan_card 推今日计划卡。

走服务：经真实 API GET /daily/plans/pool 取候选池（Service 只读预查询），
模拟 Skill 决策（选今日 3 任务 + 1 前置），直调 Service 推卡方法（推卡逻辑在 Service，§11）。

executor 推断（铁律§8，Skill 职责，e2e 测服务按规则填）：
  learning/research/source -> human；dev/survey -> agent
vision 全 learning，故 executor=human。

S3 流程：推今日计划卡 -> 用户勾选任务+前置 -> 点「确认今日计划」->
INSERT daily_records/daily_tasks/subtasks(前置) + executor 推断落库。
"""

import httpx
from sqlalchemy import text

from app.config import settings
from app.db.session import SessionLocal
from app.services.daily_app_svc import DailyAppSvc

API = "http://localhost:8001"
CHAT_ID = settings.feishu_default_chat_id
_DATE = "2026-07-13"  # 与 pool 返回的 today 一致

# 模拟 Skill 生成的前置（subtask_id 用确定性 UUID，与 checker name pre_<id> 配对）
PREREQ_NAME = "环境准备：确认 Obsidian 仓库可写"


def main() -> None:
    # 1. 真实 API 取候选池
    resp = httpx.get(f"{API}/api/v1/daily/plans/pool", params={"user_id": "feishu_user"}, timeout=10)
    resp.raise_for_status()
    pool = resp.json()["data"]
    print(f"[pool] {len(pool['active_phases'])} 激活阶段, {len(pool['pending_tasks'])} 待执行任务")

    # 2. 模拟 Skill 决策：选 3 个任务（每阶段第 1 个：理论推导）
    pending = pool["pending_tasks"]
    # 按阶段分组取每组第 1 个
    by_phase: dict[str, dict] = {}
    for t in pending:
        if t["phase_id"] not in by_phase:
            by_phase[t["phase_id"]] = t
    chosen = list(by_phase.values())[:3]
    candidate_tasks = [
        {
            "task_id": t["task_id"],
            "name": t["name"],
            "executor": "human",  # learning -> human（铁律§8）
            "phase_info": f"{t['phase_name']}",
        }
        for t in chosen
    ]
    print(f"[候选] 今日 {len(candidate_tasks)} 任务:")
    for c in candidate_tasks:
        print(f"  - {c['name']} | {c['phase_info']} | executor=human")

    # 3. 前置（用确定性 subtask_id）
    prereq_id = "pre-env-prepare-0001"
    prerequisites = [{"subtask_id": prereq_id, "name": PREREQ_NAME}]
    print(f"[前置] {PREREQ_NAME}")

    # 4. 直调 Service 推卡方法
    with SessionLocal() as db:
        message_id = DailyAppSvc(db).push_daily_plan_card(
            date_str=_DATE,
            candidate_tasks=candidate_tasks,
            prerequisites=prerequisites,
            chat_id=CHAT_ID,
        )
    if not message_id:
        raise SystemExit("[FAIL] send_card 未返回 message_id")
    print(f"\n[OK] 今日计划卡已推: message_id = {message_id}")
    print(f"[card_registry] type=daily_plan, date={_DATE}, prerequisites=1")
    print("\n>>> 请在飞书卡片上：")
    print("    1. 勾选 3 个候选任务（理论推导）")
    print("    2. 前置「环境准备」勾选保留（或取消均可）")
    print("    3. 点「确认今日计划」")
    print(f"\n>>> message_id={message_id}")


if __name__ == "__main__":
    main()
