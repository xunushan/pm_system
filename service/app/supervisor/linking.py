"""阶段衔接建议逻辑（doc/03 §3.3）：查下一阶段 + 推算 deadline。

纯确定性代码（非 LLM，铁律 §3#1）。被 handlers 和 stats_app_svc 共用：
  - handlers.on_phase_completed: 阶段完成事件后推衔接卡片
  - stats_app_svc.get_weekly_stats: 周统计填充 supervisor_linking_status

Step 1: 查同专题 sort_order+1 下一阶段（强约束，自动锁定）
Step 2: 推算建议 deadline（剩余时间 / 剩余阶段数，结合任务数微调）
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.times import now_utc_naive
from app.models.goal import Goal
from app.models.phase import Phase
from app.models.task import Task
from app.models.theme import Theme

# 无 time_range_end 时，每阶段默认天数
_DEFAULT_DAYS_PER_PHASE = 7


def find_next_phase(db: Session, phase_id: str) -> Phase | None:
    """查同专题 sort_order+1 的下一阶段（doc/03 §3.3 Step1）。

    强约束：阶段按 sort_order 顺序激活。下一阶段 = 同 theme_id 中 sort_order
    比当前阶段大 1 的阶段。返回 None 表示无下一阶段（专题将完成）。
    """
    phase = db.get(Phase, phase_id)
    if phase is None:
        return None
    return db.scalar(
        select(Phase).where(
            Phase.theme_id == phase.theme_id,
            Phase.sort_order == phase.sort_order + 1,
        )
    )


def compute_suggested_deadline(db: Session, next_phase: Phase) -> date | None:
    """推算建议 deadline（doc/03 §3.3 Step2）。

    逻辑（纯计算）：
      - 剩余时间 = goal.time_range_end - today（无 time_range_end 用默认 7 天/阶段）
      - 剩余阶段数 = 同专题未开始阶段数（含 next_phase）
      - 建议每阶段天数 = 剩余时间 / 剩余阶段数（向下取整，最少 1 天）
      - suggested_deadline = today + 每阶段天数

    结合任务数微调：next_phase 任务数 > 5 时额外 +1 天。
    """
    today = now_utc_naive().date()
    theme = db.get(Theme, next_phase.theme_id)
    if theme is None:
        return today + timedelta(days=_DEFAULT_DAYS_PER_PHASE)

    goal = db.get(Goal, theme.goal_id)

    # 剩余阶段数：同专题未开始阶段数（含 next_phase）
    remaining_phases = list(
        db.scalars(
            select(Phase).where(
                Phase.theme_id == next_phase.theme_id,
                Phase.status == "未开始",
            )
        )
    )
    n_remaining = max(len(remaining_phases), 1)

    # 剩余时间
    if goal is not None and goal.time_range_end is not None:
        remaining_days = (goal.time_range_end - today).days
        if remaining_days <= 0:
            days_per_phase = 1
        else:
            days_per_phase = max(remaining_days // n_remaining, 1)
    else:
        days_per_phase = _DEFAULT_DAYS_PER_PHASE

    # 结合任务数微调：任务多则多给 1 天
    task_count = db.query(Task).filter(Task.phase_id == next_phase.id).count()
    if task_count > 5:
        days_per_phase += 1

    return today + timedelta(days=days_per_phase)


def get_linking_status(db: Session) -> tuple[str | None, date | None]:
    """获取当前衔接状态（供 stats_app_svc.get_weekly_stats 填充）。

    逻辑：
      1. 找「当前进行中」或「最近完成」的阶段（已激活 activated_at 有值，非已暂停）
      2. 查其同专题 sort_order+1 下一阶段
      3. 推算 suggested_deadline
      4. 无下一阶段（专题将完成）-> (None, None)

    Returns:
        (next_phase_id, suggested_deadline)，无下一阶段时均为 None。
    """
    # 找当前进行中的阶段（优先）或最近完成的阶段
    current = db.scalar(
        select(Phase)
        .where(
            Phase.activated_at.is_not(None),
            Phase.status == "进行中",
        )
        .order_by(Phase.status_changed_at.desc())
    )
    if current is None:
        # 无进行中的，找最近完成的
        current = db.scalar(
            select(Phase)
            .where(
                Phase.activated_at.is_not(None),
                Phase.status == "已完成",
            )
            .order_by(Phase.completed_at.desc())
        )
    if current is None:
        return None, None

    next_phase = find_next_phase(db, current.id)
    if next_phase is None:
        return None, None

    deadline = compute_suggested_deadline(db, next_phase)
    return next_phase.id, deadline
