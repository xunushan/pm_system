"""cascade_revert_entity 单元测试（S9 board 用）：从 phase/theme/goal 起点向上回退。

关键规则：
  - 不向下回退子级（最小回退原则，DB 唯一真相源）。
  - 只动'已完成'的上级（进行中/未开始/已暂停均不动）。
  - 遇到第一个非'已完成'即停。
  - task 起点委托给 S5 既有 cascade_revert（行为不变）。
"""

from app.core import cascade
from app.models.status_change_log import StatusChangeLog
from app.models.task import Task
from tests._factory import make_tree


def _setup_completed_tree(db_session, *, tasks_per_phase=1, n_themes=1, phases_per_theme=1):
    """建树 + 激活 + 全完成（phase/theme/goal 均'已完成'）。

    返回 (goal, themes, phases, tasks_by_phase)。
    """
    goal, themes, phases, tasks_by_phase = _setup_active_tree(
        db_session,
        tasks_per_phase=tasks_per_phase,
        n_themes=n_themes,
        phases_per_theme=phases_per_theme,
    )
    # 完成所有 task -> 级联完成 phase/theme/goal
    for phase_tasks in tasks_by_phase.values():
        for t in phase_tasks:
            t.status = "已完成"
    db_session.flush()
    first_task = list(tasks_by_phase.values())[0][0]
    cascade.cascade_status(db_session, "task", first_task.id)
    db_session.flush()
    return goal, themes, phases, tasks_by_phase


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


# ===== phase 起点向上回退（不向下回退子 task）=====


def test_cascade_revert_entity_phase_pulls_theme_goal(db_session):
    """phase revert -> theme/goal 已完成 -> 拉回进行中，子 task 完成态保留。"""
    goal, themes, phases, tasks_by_phase = _setup_completed_tree(db_session, tasks_per_phase=1)
    phase = phases[0]
    assert phase.status == "已完成"
    assert themes[0].status == "已完成"
    assert goal.status == "已完成"

    # phase 自身已被 BoardAppSvc 回退（模拟），cascade 只处理向上
    phase.status = "进行中"
    phase.completed_at = None
    db_session.flush()

    result = cascade.cascade_revert_entity(db_session, "phase", phase.id)
    db_session.flush()

    assert result["theme_reverted"] is True
    assert result["goal_reverted"] is True
    assert result["theme_id"] == themes[0].id
    assert result["goal_id"] == goal.id
    assert themes[0].status == "进行中"
    assert goal.status == "进行中"
    # 子 task 完成态保留（不向下回退）
    assert tasks_by_phase[phase.id][0].status == "已完成"


def test_cascade_revert_entity_phase_does_not_revert_subtasks(db_session):
    """phase revert -> 子 task 完成态保留（不向下回退子级）。"""
    goal, themes, phases, tasks_by_phase = _setup_completed_tree(db_session, tasks_per_phase=2)
    phase = phases[0]
    phase.status = "进行中"
    phase.completed_at = None
    db_session.flush()

    cascade.cascade_revert_entity(db_session, "phase", phase.id)
    db_session.flush()

    # 所有子 task 仍是已完成
    for t in tasks_by_phase[phase.id]:
        assert t.status == "已完成"


def test_cascade_revert_entity_phase_stops_at_non_completed_theme(db_session):
    """phase revert -> theme 不是已完成 -> theme/goal 不动。"""
    goal, themes, phases, tasks_by_phase = _setup_completed_tree(
        db_session, tasks_per_phase=1, phases_per_theme=2
    )
    # 只完成 phase[0]，phase[1] 未完成 -> theme 进行中
    phase0 = phases[0]
    assert phase0.status == "已完成"
    # theme 不一定是已完成（phase[1] 未完成）
    # 手动把 theme/goal 设为进行中
    themes[0].status = "进行中"
    goal.status = "进行中"
    db_session.flush()

    phase0.status = "进行中"
    phase0.completed_at = None
    db_session.flush()

    result = cascade.cascade_revert_entity(db_session, "phase", phase0.id)
    db_session.flush()

    assert result["theme_reverted"] is False
    assert result["goal_reverted"] is False
    assert themes[0].status == "进行中"
    assert goal.status == "进行中"


# ===== theme 起点向上回退 =====


def test_cascade_revert_entity_theme_pulls_goal(db_session):
    """theme revert -> goal 已完成 -> 拉回进行中。"""
    goal, themes, phases, tasks_by_phase = _setup_completed_tree(db_session, tasks_per_phase=1)
    # theme 自身已被 BoardAppSvc 回退（模拟）
    themes[0].status = "进行中"
    db_session.flush()

    result = cascade.cascade_revert_entity(db_session, "theme", themes[0].id)
    db_session.flush()

    assert result["goal_reverted"] is True
    assert result["goal_id"] == goal.id
    assert goal.status == "进行中"
    # theme 已被 BoardAppSvc 回退，cascade 不再动 theme
    assert result["theme_reverted"] is False


def test_cascade_revert_entity_theme_stops_when_goal_not_completed(db_session):
    """theme revert -> goal 进行中 -> 不动。"""
    goal, themes, phases, tasks_by_phase = _setup_completed_tree(db_session, tasks_per_phase=1)
    goal.status = "进行中"
    themes[0].status = "进行中"
    db_session.flush()

    result = cascade.cascade_revert_entity(db_session, "theme", themes[0].id)
    db_session.flush()

    assert result["goal_reverted"] is False
    assert goal.status == "进行中"


# ===== goal 起点无上级 =====


def test_cascade_revert_entity_goal_no_cascade(db_session):
    """goal revert -> 无上级 -> 无级联（仅返回全 False）。"""
    goal, themes, phases, tasks_by_phase = _setup_completed_tree(db_session, tasks_per_phase=1)
    # goal 自身已被 BoardAppSvc 回退（模拟）
    goal.status = "进行中"
    db_session.flush()

    result = cascade.cascade_revert_entity(db_session, "goal", goal.id)
    db_session.flush()

    assert result["phase_reverted"] is False
    assert result["theme_reverted"] is False
    assert result["goal_reverted"] is False


# ===== task 起点委托给 cascade_revert（行为不变）=====


def test_cascade_revert_entity_task_delegates_to_cascade_revert(db_session):
    """task revert -> 委托给 cascade_revert，行为不变 + 补 ID 字段。"""
    goal, themes, phases, tasks_by_phase = _setup_completed_tree(db_session, tasks_per_phase=1)
    phase = phases[0]
    task = tasks_by_phase[phase.id][0]

    # task 自身已被回退（模拟）
    task.status = "待执行"
    task.completed_at = None
    db_session.flush()

    result = cascade.cascade_revert_entity(db_session, "task", task.id)
    db_session.flush()

    assert result["phase_reverted"] is True
    assert result["theme_reverted"] is True
    assert result["goal_reverted"] is True
    assert result["phase_id"] == phase.id
    assert result["theme_id"] == themes[0].id
    assert result["goal_id"] == goal.id
    assert phase.status == "进行中"
    assert themes[0].status == "进行中"
    assert goal.status == "进行中"


# ===== 审计日志 =====


def test_cascade_revert_entity_writes_cascade_audit(db_session):
    """phase revert -> cascade 对 theme/goal 各写一条 cascade 审计。"""
    goal, themes, phases, tasks_by_phase = _setup_completed_tree(db_session, tasks_per_phase=1)
    phase = phases[0]
    # 清除完成级联的审计
    db_session.query(StatusChangeLog).filter(StatusChangeLog.change_type == "cascade").delete()
    db_session.flush()

    phase.status = "进行中"
    phase.completed_at = None
    db_session.flush()

    cascade.cascade_revert_entity(db_session, "phase", phase.id)
    db_session.flush()

    logs = (
        db_session.query(StatusChangeLog)
        .filter(StatusChangeLog.change_type == "cascade")
        .order_by(StatusChangeLog.changed_at)
        .all()
    )
    # 2 条：theme + goal（phase 自身由 BoardAppSvc 回退，不在 cascade）
    assert len(logs) == 2
    assert {log.entity_type for log in logs} == {"theme", "goal"}
    for log in logs:
        assert log.from_status == "已完成"
        assert log.to_status == "进行中"
        assert log.triggered_by == "cascade"


# ===== 不存在的实体 =====


def test_cascade_revert_entity_unknown_entity_is_noop(db_session):
    """不存在的 entity_id -> noop，返回全 False + None IDs。"""
    result = cascade.cascade_revert_entity(db_session, "phase", "no-such-id")
    assert result["phase_reverted"] is False
    assert result["theme_reverted"] is False
    assert result["goal_reverted"] is False
    assert result["phase_id"] is None
    assert result["theme_id"] is None
    assert result["goal_id"] is None
