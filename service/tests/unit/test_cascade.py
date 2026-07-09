"""cascade 单元测试：激活级联（phase 进行中 -> theme/goal 未开始->进行中）。

注意：本测试的"激活级联"与 doc/02 2.15 的"完成级联"方向相反（激活向上 vs 完成向上）。
完成级联由 S4B/S5 实现。
"""

from app.core import cascade
from app.models.status_change_log import StatusChangeLog
from tests._factory import make_tree


def test_cascade_activates_theme_and_goal(db_session):
    """phase 激活后向上级联：theme/goal 未开始 -> 进行中，各写 cascade 审计。"""
    goal, themes, phases = make_tree(db_session)
    phase = phases[0]
    theme = themes[0]
    # 模拟 phase 已被设为进行中（调用方职责）
    phase.status = "进行中"
    db_session.flush()

    cascade.cascade_status(db_session, "phase", phase.id)

    db_session.flush()
    assert theme.status == "进行中"
    assert goal.status == "进行中"
    # 2 条 cascade 审计（theme + goal）
    cascade_logs = (
        db_session.query(StatusChangeLog).filter(StatusChangeLog.change_type == "cascade").all()
    )
    assert len(cascade_logs) == 2
    assert {log.entity_type for log in cascade_logs} == {"theme", "goal"}


def test_cascade_idempotent_when_already_active(db_session):
    """theme/goal 已进行中时，级联不重复改、不重复写日志（幂等）。"""
    goal, themes, phases = make_tree(db_session)
    phase = phases[0]
    theme = themes[0]
    # theme/goal 已进行中（如之前已级联过）
    theme.status = "进行中"
    goal.status = "进行中"
    phase.status = "进行中"
    db_session.flush()

    cascade.cascade_status(db_session, "phase", phase.id)

    db_session.flush()
    assert theme.status == "进行中"
    assert goal.status == "进行中"
    assert db_session.query(StatusChangeLog).filter_by(change_type="cascade").count() == 0


def test_cascade_non_phase_entity_is_noop(db_session):
    """非 phase 实体（如 task）当前不触发级联（完成级联留 S5）。"""
    cascade.cascade_status(db_session, "task", "no-such-id")  # 不抛异常


def test_cascade_unknown_phase_is_noop(db_session):
    cascade.cascade_status(db_session, "phase", "no-such-id")  # 不抛异常
