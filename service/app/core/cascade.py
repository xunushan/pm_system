"""即时级联：状态变更时事务内向上推导。

级联分两类（doc/02 2.15）：
  - 激活级联（Story2）：phase 未开始->进行中 时，向上把仍"未开始"的 theme/goal 设"进行中"。
  - 完成级联（doc/02 2.15）：task 完成->阶段全完成?->phase 完成->theme 完成->goal 完成。
    此类由 S4B/S5 实现，本文件留 TODO。

所有级联变更写 status_change_log（change_type='cascade', triggered_by='cascade'）。
只动"未开始"的上级（幂等：已进行中的不重复改、不重复写日志），满足重复激活同专题另一阶段。
事务内纯 DB（<200ms），满足飞书 3 秒回调。
"""

from sqlalchemy.orm import Session

from app.core import audit
from app.core.times import now_utc_naive
from app.models.goal import Goal
from app.models.phase import Phase
from app.models.theme import Theme


def cascade_status(db: Session, entity_type: str, entity_id: str) -> None:
    """状态变更后事务内向上级联。

    Story2 范围：entity_type='phase' 的激活级联（未开始->进行中 向上传播）。
    其他类型（task 完成级联）留 S4B/S5。

    幂等：仅把仍为"未开始"的 theme/goal 推进到"进行中"，已进行中的不动。
    """
    if entity_type != "phase":
        # TODO(S4B/S5): 完成级联（task 完成 -> phase 完成 -> theme 完成 -> goal 完成）
        return

    phase = db.get(Phase, entity_id)
    if phase is None:
        return

    theme = db.get(Theme, phase.theme_id)
    if theme is not None and theme.status == "未开始":
        _activate(db, "theme", theme, "进行中")

    goal = db.get(Goal, theme.goal_id) if theme is not None else None
    if goal is not None and goal.status == "未开始":
        _activate(db, "goal", goal, "进行中")


def _activate(db: Session, entity_type: str, entity, to_status: str) -> None:
    """把单个上级实体从'未开始'推进到 to_status，写 cascade 审计。"""
    from_status = entity.status
    entity.status = to_status
    entity.status_changed_at = now_utc_naive()
    audit.log_status_change(
        db,
        entity_type=entity_type,
        entity_id=entity.id,
        from_status=from_status,
        to_status=to_status,
        change_type="cascade",
        triggered_by="cascade",
    )
