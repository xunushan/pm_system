"""StatsAppSvc.get_weekly_stats 单元测试：周统计各字段正确 + supervisor_linking_status 占位 None。

直接调 AppSvc（不经 HTTP），用 db_session 断言。HTTP 链路见 integration。
"""

from datetime import date, datetime
from uuid import uuid4

import pytest

from app.core.exceptions import BadRequestError
from app.models.daily_record import DailyRecord
from app.models.daily_task import DailyTask
from app.models.subtask import Subtask
from app.models.task import Task
from app.models.workspace import Workspace
from app.models.workspace_progress import WorkspaceProgress
from app.services.stats_app_svc import StatsAppSvc
from tests._factory import make_tree

_WEEK = "2026-W27"
_START = date(2026, 6, 29)  # 周一
_END = date(2026, 7, 5)  # 周日
_DAY2 = date(2026, 6, 30)
# 本周内某时刻（用于 subtask.created_at 过滤）
_WEEK_DT = datetime(2026, 6, 30, 12, 0, 0)


def _setup_week(db, *, tasks_per_phase=2, completed_count=1):
    """建树 + 激活 + 首日 daily_record + daily_tasks。返回 (goal, themes, phases, tasks, daily)。"""
    goal, themes, phases = make_tree(
        db, n_themes=1, phases_per_theme=1, tasks_per_phase=tasks_per_phase
    )
    goal.status = "进行中"
    themes[0].status = "进行中"
    phases[0].status = "进行中"
    phases[0].activated_at = _START
    db.flush()

    tasks = list(db.query(Task).filter_by(phase_id=phases[0].id).order_by(Task.sort_order))
    for i, t in enumerate(tasks):
        if i < completed_count:
            t.status = "已完成"
    db.flush()

    daily = DailyRecord(
        id=str(uuid4()),
        date=_START,
        week=_WEEK,
        push_source="manual",
        is_confirmed=False,
    )
    db.add(daily)
    db.flush()
    for t in tasks:
        db.add(DailyTask(id=str(uuid4()), daily_id=daily.id, task_id=t.id))
    db.flush()
    return goal, themes, phases, tasks, daily


def _add_workspace_and_progress(db, theme, task):
    """建 workspace + workspace_progress（本周内）。"""
    ws = Workspace(
        id=str(uuid4()),
        theme_id=theme.id,
        path=f"data/workspaces/{uuid4().hex[:8]}",
        managed=True,
        status="已就绪",
        type="dev",
    )
    db.add(ws)
    db.flush()
    db.add(
        WorkspaceProgress(
            id=str(uuid4()),
            workspace_id=ws.id,
            date=_START,
            task_id=task.id,
            file_path="notes/day1.md",
            file_type="note",
        )
    )
    db.add(
        WorkspaceProgress(
            id=str(uuid4()),
            workspace_id=ws.id,
            date=_DAY2,
            task_id=task.id,
            file_path="src/main.py",
            file_type="code",
        )
    )
    db.flush()
    return ws


def test_get_weekly_stats_structure(db_session):
    """get_weekly_stats 返回完整结构 + 7 天 daily_stats。"""
    goal, themes, phases, tasks, daily = _setup_week(
        db_session, tasks_per_phase=2, completed_count=1
    )

    data = StatsAppSvc(db_session).get_weekly_stats("u1", _WEEK)

    assert data.week == _WEEK
    assert data.date_range.start == _START
    assert data.date_range.end == _END
    # daily_stats: 7 天
    assert len(data.daily_stats) == 7
    first = data.daily_stats[0]
    assert first.date == _START
    assert first.completed_count == 1
    assert first.incomplete_count == 1
    assert first.is_confirmed is False
    # 无 daily_record 的天补 0
    second = data.daily_stats[1]
    assert second.date == _DAY2
    assert second.completed_count == 0
    assert second.incomplete_count == 0
    # phase_health
    assert len(data.phase_health) == 1
    ph = data.phase_health[0]
    assert ph.completed == 1
    assert ph.total == 2
    # agent_output_stats 空（无 workspace_progress）
    assert data.agent_output_stats.total_files == 0
    assert data.agent_output_stats.by_type == {}
    # subtask_stats 空（无 subtask）
    assert data.subtask_stats.pre.total == 0
    assert data.subtask_stats.post.total == 0
    # supervisor_linking_status 占位（字段为 None）
    assert data.supervisor_linking_status is not None
    assert data.supervisor_linking_status.next_phase is None
    assert data.supervisor_linking_status.suggested_deadline is None


def test_get_weekly_stats_agent_output_aggregation(db_session):
    """agent_output_stats 按 file_type 聚合本周 workspace_progress。"""
    goal, themes, phases, tasks, daily = _setup_week(
        db_session, tasks_per_phase=1, completed_count=0
    )
    _add_workspace_and_progress(db_session, themes[0], tasks[0])

    data = StatsAppSvc(db_session).get_weekly_stats("u1", _WEEK)

    assert data.agent_output_stats.total_files == 2
    assert data.agent_output_stats.by_type == {"note": 1, "code": 1}


def test_get_weekly_stats_subtask_aggregation(db_session):
    """subtask_stats 按前置/后置分类（本周创建的 subtask）。"""
    goal, themes, phases, tasks, daily = _setup_week(
        db_session, tasks_per_phase=1, completed_count=0
    )
    # 2 个前置（1 完成 1 待执行）+ 1 个后置（待执行）
    db_session.add(
        Subtask(
            id=str(uuid4()),
            task_id=tasks[0].id,
            sort_order=1,
            name="前置1",
            type="前置",
            status="已完成",
            created_at=_WEEK_DT,
        )
    )
    db_session.add(
        Subtask(
            id=str(uuid4()),
            task_id=tasks[0].id,
            sort_order=2,
            name="前置2",
            type="前置",
            status="待执行",
            created_at=_WEEK_DT,
        )
    )
    db_session.add(
        Subtask(
            id=str(uuid4()),
            task_id=tasks[0].id,
            sort_order=3,
            name="后置1",
            type="后置",
            status="待执行",
            created_at=_WEEK_DT,
        )
    )
    db_session.flush()

    data = StatsAppSvc(db_session).get_weekly_stats("u1", _WEEK)

    assert data.subtask_stats.pre.total == 2
    assert data.subtask_stats.pre.completed == 1
    assert data.subtask_stats.pre.pending == 1
    assert data.subtask_stats.post.total == 1
    assert data.subtask_stats.post.completed == 0
    assert data.subtask_stats.post.pending == 1


def test_get_weekly_stats_excludes_out_of_range_subtasks(db_session):
    """本周外创建的 subtask 不计入（created_at 过滤）。"""
    goal, themes, phases, tasks, daily = _setup_week(
        db_session, tasks_per_phase=1, completed_count=0
    )
    # 上周创建的 subtask
    db_session.add(
        Subtask(
            id=str(uuid4()),
            task_id=tasks[0].id,
            sort_order=1,
            name="上周前置",
            type="前置",
            status="已完成",
            created_at=datetime(2026, 6, 20, 12, 0, 0),
        )
    )
    db_session.flush()

    data = StatsAppSvc(db_session).get_weekly_stats("u1", _WEEK)

    assert data.subtask_stats.pre.total == 0


def test_get_weekly_stats_empty_week(db_session):
    """无任何数据的一周 -> daily_stats 7 天补 0，其余统计空。"""
    data = StatsAppSvc(db_session).get_weekly_stats("u1", _WEEK)

    assert data.week == _WEEK
    assert len(data.daily_stats) == 7
    assert all(d.completed_count == 0 for d in data.daily_stats)
    assert all(d.incomplete_count == 0 for d in data.daily_stats)
    assert data.phase_health == []
    assert data.agent_output_stats.total_files == 0
    assert data.subtask_stats.pre.total == 0
    assert data.subtask_stats.post.total == 0
    assert data.supervisor_linking_status.next_phase is None


def test_get_weekly_stats_daily_confirmed_flag(db_session):
    """daily_stats 反映 daily_record.is_confirmed。"""
    goal, themes, phases, tasks, daily = _setup_week(
        db_session, tasks_per_phase=1, completed_count=1
    )
    daily.is_confirmed = True
    db_session.flush()

    data = StatsAppSvc(db_session).get_weekly_stats("u1", _WEEK)

    assert data.daily_stats[0].is_confirmed is True


@pytest.mark.parametrize("bad_week", ["2026W27", "2026-27", "W27", "", "abc-W27"])
def test_parse_week_invalid_format_raises(bad_week):
    """非法 ISO 周格式 -> BadRequestError。"""
    with pytest.raises(BadRequestError):
        StatsAppSvc._parse_week(bad_week)


def test_parse_week_valid():
    """合法 ISO 周解析为周一/周日。"""
    start, end = StatsAppSvc._parse_week("2026-W27")
    assert start == date(2026, 6, 29)
    assert end == date(2026, 7, 5)
