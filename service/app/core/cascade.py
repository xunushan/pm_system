"""即时级联：状态变更时事务内向上推导。

级联分三类（doc/02 2.15-2.16）：
  - 激活级联（Story2）：phase 未开始->进行中 时，向上把仍"未开始"的 theme/goal 设"进行中"。
  - 完成级联（Story4B）：task 完成->阶段全完成?->phase 完成->专题全完成?->goal 完成。
  - 回退级联（Story5）：task 回退->phase 若"已完成"拉回"进行中"
    ->theme 若"已完成"拉回->goal 若"已完成"拉回。

所有级联变更写 status_change_log（change_type='cascade', triggered_by='cascade'）。
幂等：激活级联只动'未开始'的；完成级联只动'进行中'的；回退级联只动'已完成'的。
事务内纯 DB（<200ms），满足飞书 3 秒回调。
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.times import now_utc_naive
from app.models.goal import Goal
from app.models.phase import Phase
from app.models.task import Task
from app.models.theme import Theme
from app.supervisor.event_bus import emit


def cascade_status(db: Session, entity_type: str, entity_id: str) -> dict:
    """状态变更后事务内向上级联。

    Story2 范围：entity_type='phase' 的激活级联（未开始->进行中 向上传播）。
    Story4B 范围：entity_type='task' 的完成级联（task 完成->阶段全完成->专题全完成->目标全完成）。

    幂等：仅推进可推进的实体（激活级联只动'未开始'的；完成级联只动'进行中'的）。

    Returns:
        完成级联返回 {phase_completed, theme_completed, goal_completed}；
        激活级联返回空 dict。调用方按需取值，忽略返回值也安全。
    """
    if entity_type == "phase":
        _cascade_activate(db, entity_id)
        return {}

    if entity_type == "task":
        return _cascade_complete(db, entity_id)

    return {}


def cascade_revert(db: Session, task_id: str) -> dict:
    """回退级联（Story5，doc/02 2.16）：task 回退后向上回退已完成的上级。

    task 已完成->待执行 后：检查其 phase，若 phase.status=='已完成' 则置'进行中'
    （清 completed_at，写 cascade 审计 + emit），然后同理检查 theme、goal。

    幂等：只动'已完成'的上级（进行中/未开始/已暂停均不动）。
    只向上回退「因该子级不再完成而不应再已完成」的上级，遇到第一个非'已完成'即停。

    Returns:
        {phase_reverted, theme_reverted, goal_reverted}
    """
    result = {"phase_reverted": False, "theme_reverted": False, "goal_reverted": False}

    task = db.get(Task, task_id)
    if task is None:
        return result

    phase = db.get(Phase, task.phase_id)
    if phase is None or phase.status != "已完成":
        return result
    _revert_cascade_status(db, "phase", phase, "进行中", clear_completed_at=True)
    emit({"type": "phase_reverted", "entity_id": phase.id})
    result["phase_reverted"] = True

    theme = db.get(Theme, phase.theme_id)
    if theme is None or theme.status != "已完成":
        return result
    _revert_cascade_status(db, "theme", theme, "进行中")
    emit({"type": "theme_reverted", "entity_id": theme.id})
    result["theme_reverted"] = True

    goal = db.get(Goal, theme.goal_id)
    if goal is None or goal.status != "已完成":
        return result
    _revert_cascade_status(db, "goal", goal, "进行中")
    emit({"type": "goal_reverted", "entity_id": goal.id})
    result["goal_reverted"] = True

    return result


# ---- 激活级联（Story2）----


def _cascade_activate(db: Session, phase_id: str) -> None:
    """激活级联：phase 进行中 -> theme/goal 仍'未开始'的推进到'进行中'。"""
    phase = db.get(Phase, phase_id)
    if phase is None:
        return

    theme = db.get(Theme, phase.theme_id)
    if theme is not None and theme.status == "未开始":
        _set_cascade_status(db, "theme", theme, "进行中")

    goal = db.get(Goal, theme.goal_id) if theme is not None else None
    if goal is not None and goal.status == "未开始":
        _set_cascade_status(db, "goal", goal, "进行中")


# ---- 完成级联（Story4B，doc/02 2.15）----


def _cascade_complete(db: Session, task_id: str) -> dict:
    """完成级联：task 完成 -> 阶段全完成? -> 专题全完成? -> 目标全完成?。

    每级检查下级是否全部'已完成'，是则把'进行中'的上级推进到'已完成'，
    写 cascade 审计 + emit 完成事件。未全部完成则不继续向上。
    幂等：只推进'进行中'的实体（已完成/未开始/已暂停均不动）。
    """
    result = {"phase_completed": False, "theme_completed": False, "goal_completed": False}

    task = db.get(Task, task_id)
    if task is None:
        return result

    phase = db.get(Phase, task.phase_id)
    if phase is None:
        return result

    # 阶段：所有任务已完成 -> phase 完成
    tasks = list(db.scalars(select(Task).where(Task.phase_id == phase.id)))
    if not tasks or not all(t.status == "已完成" for t in tasks):
        return result
    if phase.status != "进行中":
        return result
    _set_cascade_status(db, "phase", phase, "已完成", completed_at=now_utc_naive())
    emit({"type": "phase_completed", "entity_id": phase.id})
    result["phase_completed"] = True

    # 专题：所有阶段已完成 -> theme 完成
    theme = db.get(Theme, phase.theme_id)
    if theme is None:
        return result
    phases = list(db.scalars(select(Phase).where(Phase.theme_id == theme.id)))
    if not phases or not all(p.status == "已完成" for p in phases):
        return result
    if theme.status != "进行中":
        return result
    _set_cascade_status(db, "theme", theme, "已完成")
    emit({"type": "theme_completed", "entity_id": theme.id})
    result["theme_completed"] = True

    # 目标：所有专题已完成 -> goal 完成
    goal = db.get(Goal, theme.goal_id)
    if goal is None:
        return result
    themes = list(db.scalars(select(Theme).where(Theme.goal_id == goal.id)))
    if not themes or not all(t.status == "已完成" for t in themes):
        return result
    if goal.status != "进行中":
        return result
    _set_cascade_status(db, "goal", goal, "已完成")
    emit({"type": "goal_completed", "entity_id": goal.id})
    result["goal_completed"] = True

    return result


def _set_cascade_status(
    db: Session, entity_type: str, entity, to_status: str, completed_at=None
) -> None:
    """推进单个实体到 to_status，写 cascade 审计。

    激活级联传 completed_at=None（无 completed_at 列或不需要设）；
    完成级联对 phase 传 completed_at=now（phase 有该列），theme/goal 无 completed_at 列传 None。
    """
    from_status = entity.status
    entity.status = to_status
    entity.status_changed_at = now_utc_naive()
    if completed_at is not None and hasattr(entity, "completed_at"):
        entity.completed_at = completed_at
    audit.log_status_change(
        db,
        entity_type=entity_type,
        entity_id=entity.id,
        from_status=from_status,
        to_status=to_status,
        change_type="cascade",
        triggered_by="cascade",
    )


def _revert_cascade_status(
    db: Session, entity_type: str, entity, to_status: str, clear_completed_at: bool = False
) -> None:
    """回退级联：把单个'已完成'实体拉回到 to_status（'进行中'），写 cascade 审计。

    回退级联对 phase 清 completed_at（phase 有该列）；theme/goal 无 completed_at 列。
    只在 cascade_revert 中调用，调用方已确保 entity.status=='已完成'。
    """
    from_status = entity.status
    entity.status = to_status
    entity.status_changed_at = now_utc_naive()
    if clear_completed_at and hasattr(entity, "completed_at"):
        entity.completed_at = None
    audit.log_status_change(
        db,
        entity_type=entity_type,
        entity_id=entity.id,
        from_status=from_status,
        to_status=to_status,
        change_type="cascade",
        triggered_by="cascade",
    )
