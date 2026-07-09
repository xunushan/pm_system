"""cascade 单元测试：激活级联 + 完成级联。

激活级联（Story2）：phase 进行中 -> theme/goal 未开始->进行中。
完成级联（Story4B，doc/02 2.15）：task 完成 -> 阶段全完成 -> phase 完成 -> 专题全完成 -> goal 完成。
"""

from app.core import cascade
from app.models.status_change_log import StatusChangeLog
from app.models.task import Task
from tests._factory import make_tree

# ===== 激活级联（Story2 回归）=====


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


def test_cascade_unknown_phase_is_noop(db_session):
    cascade.cascade_status(db_session, "phase", "no-such-id")  # 不抛异常


def test_cascade_activate_returns_empty_dict(db_session):
    """激活级联返回空 dict（无完成信息）。"""
    goal, themes, phases = make_tree(db_session)
    phases[0].status = "进行中"
    db_session.flush()
    result = cascade.cascade_status(db_session, "phase", phases[0].id)
    assert result == {}


# ===== 完成级联（Story4B，doc/02 2.15）=====


def _setup_active_tree(db_session, *, tasks_per_phase=2, n_themes=1, phases_per_theme=1):
    """建树并激活（phase/theme/goal 均设为进行中），返回 (goal, themes, phases, tasks_by_phase)。"""
    goal, themes, phases = make_tree(
        db_session,
        n_themes=n_themes,
        phases_per_theme=phases_per_theme,
        tasks_per_phase=tasks_per_phase,
    )
    goal.status = "进行中"
    for theme in themes:
        theme.status = "进行中"
    for phase in phases:
        phase.status = "进行中"
    db_session.flush()

    tasks_by_phase = {}
    for phase in phases:
        tasks_by_phase[phase.id] = list(
            db_session.query(Task).filter(Task.phase_id == phase.id).order_by(Task.sort_order)
        )
    return goal, themes, phases, tasks_by_phase


def test_cascade_completes_phase_when_all_tasks_done(db_session):
    """task 全完成 -> phase 完成（theme/goal 仍进行中，因还有未完成 phase 或 phase 不全完成）。"""
    goal, themes, phases, tasks_by_phase = _setup_active_tree(db_session, tasks_per_phase=2)
    phase = phases[0]
    # 完成该 phase 下所有 task
    for t in tasks_by_phase[phase.id]:
        t.status = "已完成"
    db_session.flush()

    result = cascade.cascade_status(db_session, "task", tasks_by_phase[phase.id][0].id)

    db_session.flush()
    assert result["phase_completed"] is True
    assert result["theme_completed"] is True  # 仅 1 phase，全完成 -> theme 也完成
    assert result["goal_completed"] is True  # 仅 1 theme，全完成 -> goal 也完成
    assert phase.status == "已完成"
    assert phase.completed_at is not None
    assert themes[0].status == "已完成"
    assert goal.status == "已完成"


def test_cascade_phase_not_completed_when_tasks_pending(db_session):
    """phase 下仍有待执行 task -> phase 不完成，不继续向上级联。"""
    goal, themes, phases, tasks_by_phase = _setup_active_tree(db_session, tasks_per_phase=3)
    phase = phases[0]
    # 只完成 2/3
    tasks = tasks_by_phase[phase.id]
    tasks[0].status = "已完成"
    tasks[1].status = "已完成"
    db_session.flush()

    result = cascade.cascade_status(db_session, "task", tasks[0].id)

    db_session.flush()
    assert result == {"phase_completed": False, "theme_completed": False, "goal_completed": False}
    assert phase.status == "进行中"
    assert themes[0].status == "进行中"
    assert goal.status == "进行中"


def test_cascade_theme_not_completed_when_phases_incomplete(db_session):
    """theme 下有多个 phase，仅 1 个全完成 -> theme 不完成。"""
    goal, themes, phases, tasks_by_phase = _setup_active_tree(
        db_session, tasks_per_phase=1, phases_per_theme=2
    )
    # 完成第 1 个 phase 的所有 task
    phase0 = phases[0]
    for t in tasks_by_phase[phase0.id]:
        t.status = "已完成"
    db_session.flush()

    result = cascade.cascade_status(db_session, "task", tasks_by_phase[phase0.id][0].id)

    db_session.flush()
    assert result["phase_completed"] is True
    assert result["theme_completed"] is False  # phase[1] 未完成
    assert result["goal_completed"] is False
    assert phase0.status == "已完成"
    assert themes[0].status == "进行中"
    assert goal.status == "进行中"


def test_cascade_goal_not_completed_when_themes_incomplete(db_session):
    """goal 下有多个 theme，仅 1 个全完成 -> goal 不完成。"""
    goal, themes, phases, tasks_by_phase = _setup_active_tree(
        db_session, tasks_per_phase=1, n_themes=2, phases_per_theme=1
    )
    # 完成第 1 个 theme 的所有 task
    phase0 = phases[0]
    for t in tasks_by_phase[phase0.id]:
        t.status = "已完成"
    db_session.flush()

    result = cascade.cascade_status(db_session, "task", tasks_by_phase[phase0.id][0].id)

    db_session.flush()
    assert result["phase_completed"] is True
    assert result["theme_completed"] is True
    assert result["goal_completed"] is False  # theme[1] 未完成
    assert goal.status == "进行中"


def test_cascade_writes_cascade_audit_for_each_level(db_session):
    """完成级联每级写一条 cascade 审计（phase + theme + goal）。"""
    goal, themes, phases, tasks_by_phase = _setup_active_tree(db_session, tasks_per_phase=1)
    phase = phases[0]
    for t in tasks_by_phase[phase.id]:
        t.status = "已完成"
    db_session.flush()

    cascade.cascade_status(db_session, "task", tasks_by_phase[phase.id][0].id)

    db_session.flush()
    cascade_logs = (
        db_session.query(StatusChangeLog)
        .filter(StatusChangeLog.change_type == "cascade")
        .order_by(StatusChangeLog.changed_at)
        .all()
    )
    # 3 条：phase + theme + goal
    assert len(cascade_logs) == 3
    assert {log.entity_type for log in cascade_logs} == {"phase", "theme", "goal"}
    for log in cascade_logs:
        assert log.to_status == "已完成"
        assert log.triggered_by == "cascade"


def test_cascade_idempotent_when_already_completed(db_session):
    """phase/theme/goal 已完成时，重复调用不重复改、不重复写日志。"""
    goal, themes, phases, tasks_by_phase = _setup_active_tree(db_session, tasks_per_phase=1)
    phase = phases[0]
    for t in tasks_by_phase[phase.id]:
        t.status = "已完成"
    db_session.flush()

    cascade.cascade_status(db_session, "task", tasks_by_phase[phase.id][0].id)
    db_session.flush()

    # 第二次调用（幂等）
    result = cascade.cascade_status(db_session, "task", tasks_by_phase[phase.id][0].id)
    db_session.flush()

    assert result == {"phase_completed": False, "theme_completed": False, "goal_completed": False}
    # 仍然只有第一次的 3 条 cascade 审计
    assert db_session.query(StatusChangeLog).filter_by(change_type="cascade").count() == 3


def test_cascade_unknown_task_is_noop(db_session):
    """不存在的 task_id -> noop，返回全 False。"""
    result = cascade.cascade_status(db_session, "task", "no-such-id")
    assert result == {"phase_completed": False, "theme_completed": False, "goal_completed": False}


def test_cascade_paused_phase_not_completed(db_session):
    """phase 为已暂停时，即使所有 task 完成，phase 也不级联完成（只推进'进行中'的）。"""
    goal, themes, phases, tasks_by_phase = _setup_active_tree(db_session, tasks_per_phase=1)
    phase = phases[0]
    phase.status = "已暂停"  # 暂停的 phase 不自动完成
    for t in tasks_by_phase[phase.id]:
        t.status = "已完成"
    db_session.flush()

    result = cascade.cascade_status(db_session, "task", tasks_by_phase[phase.id][0].id)

    db_session.flush()
    assert result["phase_completed"] is False
    assert phase.status == "已暂停"


# ===== 回退级联（Story5，doc/02 2.16 revert 触发即时重算级联）=====


def test_cascade_revert_pulls_phase_back_to_active(db_session):
    """task 回退 -> phase 已完成 -> 拉回'进行中'（清 completed_at + cascade 审计 + emit）。"""
    goal, themes, phases, tasks_by_phase = _setup_active_tree(db_session, tasks_per_phase=1)
    phase = phases[0]
    # 先完成所有 task -> phase/theme/goal 完成
    for t in tasks_by_phase[phase.id]:
        t.status = "已完成"
    db_session.flush()
    cascade.cascade_status(db_session, "task", tasks_by_phase[phase.id][0].id)
    db_session.flush()
    assert phase.status == "已完成"
    assert phase.completed_at is not None

    # 回退 task -> 待执行
    task = tasks_by_phase[phase.id][0]
    task.status = "待执行"
    db_session.flush()

    result = cascade.cascade_revert(db_session, task.id)
    db_session.flush()

    assert result["phase_reverted"] is True
    assert result["theme_reverted"] is True
    assert result["goal_reverted"] is True
    assert phase.status == "进行中"
    assert phase.completed_at is None
    assert themes[0].status == "进行中"
    assert goal.status == "进行中"


def test_cascade_revert_stops_at_first_non_completed(db_session):
    """task 回退 -> phase 已完成 -> 拉回；但 theme 未完成 -> theme/goal 不动。"""
    goal, themes, phases, tasks_by_phase = _setup_active_tree(
        db_session, tasks_per_phase=1, phases_per_theme=2
    )
    # 只完成 phase[0]
    phase0 = phases[0]
    for t in tasks_by_phase[phase0.id]:
        t.status = "已完成"
    db_session.flush()
    cascade.cascade_status(db_session, "task", tasks_by_phase[phase0.id][0].id)
    db_session.flush()
    assert phase0.status == "已完成"
    assert themes[0].status == "进行中"  # phase[1] 未完成 -> theme 不完成

    # 回退 task
    task = tasks_by_phase[phase0.id][0]
    task.status = "待执行"
    db_session.flush()

    result = cascade.cascade_revert(db_session, task.id)
    db_session.flush()

    assert result["phase_reverted"] is True
    assert result["theme_reverted"] is False  # theme 本来就不是已完成
    assert result["goal_reverted"] is False
    assert phase0.status == "进行中"
    assert themes[0].status == "进行中"
    assert goal.status == "进行中"


def test_cascade_revert_idempotent_when_phase_not_completed(db_session):
    """phase 不在'已完成'时，回退级联不改动任何上级（幂等）。"""
    goal, themes, phases, tasks_by_phase = _setup_active_tree(db_session, tasks_per_phase=2)
    phase = phases[0]
    # 完成 1/2 task -> phase 仍进行中
    tasks = tasks_by_phase[phase.id]
    tasks[0].status = "已完成"
    db_session.flush()

    result = cascade.cascade_revert(db_session, tasks[0].id)
    db_session.flush()

    assert result == {"phase_reverted": False, "theme_reverted": False, "goal_reverted": False}
    assert phase.status == "进行中"
    assert themes[0].status == "进行中"
    assert goal.status == "进行中"


def test_cascade_revert_writes_cascade_audit(db_session):
    """回退级联每级写一条 cascade 审计（from=已完成, to=进行中, triggered_by=cascade）。"""
    goal, themes, phases, tasks_by_phase = _setup_active_tree(db_session, tasks_per_phase=1)
    phase = phases[0]
    for t in tasks_by_phase[phase.id]:
        t.status = "已完成"
    db_session.flush()
    cascade.cascade_status(db_session, "task", tasks_by_phase[phase.id][0].id)
    db_session.flush()

    # 清除完成级联的审计日志，只测回退级联
    db_session.query(StatusChangeLog).filter(StatusChangeLog.change_type == "cascade").delete()
    db_session.flush()

    task = tasks_by_phase[phase.id][0]
    task.status = "待执行"
    db_session.flush()

    cascade.cascade_revert(db_session, task.id)
    db_session.flush()

    revert_logs = (
        db_session.query(StatusChangeLog)
        .filter(StatusChangeLog.change_type == "cascade")
        .order_by(StatusChangeLog.changed_at)
        .all()
    )
    # 3 条：phase + theme + goal
    assert len(revert_logs) == 3
    assert {log.entity_type for log in revert_logs} == {"phase", "theme", "goal"}
    for log in revert_logs:
        assert log.from_status == "已完成"
        assert log.to_status == "进行中"
        assert log.triggered_by == "cascade"


def test_cascade_revert_does_not_touch_paused_or_not_started(db_session):
    """上级为'已暂停'或'未开始'时，回退级联不改动（只动'已完成'的）。"""
    goal, themes, phases, tasks_by_phase = _setup_active_tree(db_session, tasks_per_phase=1)
    phase = phases[0]
    # 完成 task -> phase/theme/goal 完成
    for t in tasks_by_phase[phase.id]:
        t.status = "已完成"
    db_session.flush()
    cascade.cascade_status(db_session, "task", tasks_by_phase[phase.id][0].id)
    db_session.flush()

    # 把 theme 设为已暂停（异常状态，测试防御）
    themes[0].status = "已暂停"
    db_session.flush()

    task = tasks_by_phase[phase.id][0]
    task.status = "待执行"
    db_session.flush()

    result = cascade.cascade_revert(db_session, task.id)
    db_session.flush()

    assert result["phase_reverted"] is True  # phase 已完成 -> 回退
    assert result["theme_reverted"] is False  # theme 已暂停 -> 不动
    assert themes[0].status == "已暂停"
    assert goal.status == "已完成"  # goal 不动（theme 没回退）


def test_cascade_revert_unknown_task_is_noop(db_session):
    """不存在的 task_id -> noop，返回全 False。"""
    result = cascade.cascade_revert(db_session, "no-such-id")
    assert result == {"phase_reverted": False, "theme_reverted": False, "goal_reverted": False}
