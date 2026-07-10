"""DailyAppSvc 单元测试：pool 查询 + confirm 事务 + 校验 + 异步触发。

直接调 AppSvc（不经 HTTP），用 db_session 断言 DB 状态。HTTP 链路见 integration。
"""

from datetime import date, timedelta
from unittest.mock import patch

import pytest

from app.core.exceptions import BadRequestError, ConflictError, NotFoundError
from app.models.daily_record import DailyRecord
from app.models.daily_task import DailyTask
from app.models.subtask import Subtask
from app.schemas.daily import PreSubtaskInput
from app.services.daily_app_svc import DailyAppSvc
from tests._factory import make_tree

_TODAY = date(2026, 7, 6)
_YESTERDAY = _TODAY - timedelta(days=1)


def _activate_phase(phase, *, deadline=date(2026, 7, 15)):
    """把 phase 设为已激活（进行中 + activated_at）。"""
    phase.status = "进行中"
    phase.activated_at = _YESTERDAY
    phase.deadline = deadline


def _confirm(db, task_ids, pre_subtasks=None, date_=_TODAY):
    return DailyAppSvc(db).confirm(
        user_id="u1",
        date_=date_,
        task_ids=task_ids,
        pre_subtasks=pre_subtasks or [],
    )


# ===== pool 查询 =====


def test_pool_returns_active_phases_and_pending_tasks(db_session):
    """pool 返回已激活阶段 + 待执行任务 + progress/remaining_tasks。"""
    goal, themes, phases = make_tree(db_session, n_themes=1, phases_per_theme=1, tasks_per_phase=3)
    _activate_phase(phases[0])
    db_session.flush()

    data = DailyAppSvc(db_session).get_plans_pool("u1", _TODAY)

    assert data.date == _TODAY
    assert len(data.active_phases) == 1
    ap = data.active_phases[0]
    assert ap.phase_id == phases[0].id
    assert ap.theme_name == themes[0].name
    assert ap.theme_type == "learning"
    assert ap.progress == "0/3"
    assert ap.remaining_tasks == 3
    assert len(data.pending_tasks) == 3
    pt = data.pending_tasks[0]
    assert pt.theme_type == "learning"
    assert pt.phase_deadline == date(2026, 7, 15)
    assert data.global_active_count == 1
    assert data.global_active_limit == 3


def test_pool_excludes_paused_phases(db_session):
    """已暂停的阶段不出现在 pool（即使 activated_at 有值）。"""
    goal, themes, phases = make_tree(db_session, n_themes=2, phases_per_theme=1, tasks_per_phase=1)
    _activate_phase(phases[0])
    phases[1].status = "已暂停"
    phases[1].activated_at = _YESTERDAY
    db_session.flush()

    data = DailyAppSvc(db_session).get_plans_pool("u1", _TODAY)

    active_ids = [p.phase_id for p in data.active_phases]
    assert phases[0].id in active_ids
    assert phases[1].id not in active_ids
    assert len(data.pending_tasks) == 1  # only phases[0]'s task


def test_pool_excludes_non_activated_phases(db_session):
    """未激活阶段（activated_at NULL）不出现在 pool。"""
    goal, themes, phases = make_tree(db_session, n_themes=2, phases_per_theme=1, tasks_per_phase=1)
    _activate_phase(phases[0])
    # phases[1] 保持未开始（activated_at NULL）
    db_session.flush()

    data = DailyAppSvc(db_session).get_plans_pool("u1", _TODAY)
    assert len(data.active_phases) == 1


def test_pool_progress_with_completed_tasks(db_session):
    """progress 正确反映已完成/总数。"""
    goal, themes, phases = make_tree(db_session, n_themes=1, phases_per_theme=1, tasks_per_phase=4)
    _activate_phase(phases[0])
    # 查 tasks 并标记 2 个完成
    from app.models.task import Task

    tasks = db_session.query(Task).filter_by(phase_id=phases[0].id).all()
    tasks[0].status = "已完成"
    tasks[1].status = "已完成"
    db_session.flush()

    data = DailyAppSvc(db_session).get_plans_pool("u1", _TODAY)
    ap = data.active_phases[0]
    assert ap.progress == "2/4"
    assert ap.remaining_tasks == 2


def test_pool_yesterday_completed(db_session):
    """yesterday_completed 返回昨日计划中已完成的任务。"""
    goal, themes, phases = make_tree(db_session, n_themes=1, phases_per_theme=1, tasks_per_phase=3)
    _activate_phase(phases[0])
    from app.models.task import Task

    tasks = db_session.query(Task).filter_by(phase_id=phases[0].id).all()
    tasks[0].status = "已完成"
    db_session.flush()

    # 建昨日 daily_record + daily_task
    dr = DailyRecord(
        id="dr-yesterday",
        date=_YESTERDAY,
        week="2026-W27",
        push_source="manual",
        is_confirmed=True,
    )
    db_session.add(dr)
    db_session.flush()
    dt = DailyTask(id="dt-1", daily_id=dr.id, task_id=tasks[0].id)
    db_session.add(dt)
    db_session.flush()

    data = DailyAppSvc(db_session).get_plans_pool("u1", _TODAY)
    assert len(data.yesterday_completed) == 1
    assert data.yesterday_completed[0].task_id == tasks[0].id
    assert data.yesterday_completed[0].phase_name == phases[0].name


def test_pool_yesterday_unconfirmed(db_session):
    """yesterday_unconfirmed=true 当昨日 daily_record 存在且未确认。"""
    goal, themes, phases = make_tree(db_session, n_themes=1, phases_per_theme=1, tasks_per_phase=1)
    _activate_phase(phases[0])
    db_session.flush()

    # 昨日 daily_record 未确认
    dr = DailyRecord(
        id="dr-yesterday",
        date=_YESTERDAY,
        week="2026-W27",
        push_source="auto",
        is_confirmed=False,
    )
    db_session.add(dr)
    db_session.flush()

    data = DailyAppSvc(db_session).get_plans_pool("u1", _TODAY)
    assert data.yesterday_unconfirmed is True

    # 确认后 -> false
    dr.is_confirmed = True
    db_session.flush()
    data2 = DailyAppSvc(db_session).get_plans_pool("u1", _TODAY)
    assert data2.yesterday_unconfirmed is False


def test_pool_no_yesterday_record(db_session):
    """无昨日 daily_record -> yesterday_completed 空 + yesterday_unconfirmed false。"""
    goal, themes, phases = make_tree(db_session, n_themes=1, phases_per_theme=1, tasks_per_phase=1)
    _activate_phase(phases[0])
    db_session.flush()

    data = DailyAppSvc(db_session).get_plans_pool("u1", _TODAY)
    assert data.yesterday_completed == []
    assert data.yesterday_unconfirmed is False


def test_pool_empty_when_no_active_phases(db_session):
    """无已激活阶段 -> pool 空。"""
    make_tree(db_session, n_themes=1, phases_per_theme=1, tasks_per_phase=2)
    db_session.flush()

    data = DailyAppSvc(db_session).get_plans_pool("u1", _TODAY)
    assert data.active_phases == []
    assert data.pending_tasks == []
    assert data.global_active_count == 0


# ===== confirm 事务 =====


def test_confirm_inserts_three_tables(db_session):
    """confirm 成功：INSERT daily_records + daily_tasks + subtasks。"""
    goal, themes, phases = make_tree(db_session, n_themes=1, phases_per_theme=1, tasks_per_phase=2)
    _activate_phase(phases[0])
    from app.models.task import Task

    tasks = db_session.query(Task).filter_by(phase_id=phases[0].id).all()
    db_session.flush()

    data = _confirm(
        db_session,
        [tasks[0].id, tasks[1].id],
        [PreSubtaskInput(name="搜集资料"), PreSubtaskInput(name="准备环境")],
    )

    assert data.task_count == 2
    assert data.pre_subtask_count == 2
    assert data.async_triggered is True
    assert data.date == _TODAY

    # daily_records（is_confirmed 应为 False，S5 日终确认时才置 true）
    dr = db_session.query(DailyRecord).one()
    assert dr.is_confirmed is False
    assert dr.confirmed_at is None
    assert dr.date == _TODAY
    assert dr.week.startswith("2026-W")

    # daily_tasks
    dts = db_session.query(DailyTask).all()
    assert len(dts) == 2

    # subtasks（前置）
    subs = db_session.query(Subtask).all()
    assert len(subs) == 2
    assert all(s.type == "前置" for s in subs)
    assert all(s.status == "待执行" for s in subs)


def test_confirm_duplicate_returns_409(db_session):
    """同日重复确认 -> 409（1003）。"""
    goal, themes, phases = make_tree(db_session, n_themes=1, phases_per_theme=1, tasks_per_phase=1)
    _activate_phase(phases[0])
    from app.models.task import Task

    task = db_session.query(Task).filter_by(phase_id=phases[0].id).one()
    db_session.flush()

    _confirm(db_session, [task.id])
    with pytest.raises(ConflictError):
        _confirm(db_session, [task.id])


def test_confirm_task_not_found_returns_404(db_session):
    """task 不存在 -> 404。"""
    goal, themes, phases = make_tree(db_session, n_themes=1, phases_per_theme=1, tasks_per_phase=1)
    _activate_phase(phases[0])
    db_session.flush()

    with pytest.raises(NotFoundError):
        _confirm(db_session, ["nonexistent-task-id"])


def test_confirm_task_not_activated_returns_400(db_session):
    """task 所属阶段未激活 -> 400。"""
    goal, themes, phases = make_tree(db_session, n_themes=1, phases_per_theme=1, tasks_per_phase=1)
    # 不激活 phase
    from app.models.task import Task

    task = db_session.query(Task).filter_by(phase_id=phases[0].id).one()
    db_session.flush()

    with pytest.raises(BadRequestError):
        _confirm(db_session, [task.id])


def test_confirm_task_paused_phase_returns_400(db_session):
    """task 所属阶段已暂停 -> 400。"""
    goal, themes, phases = make_tree(db_session, n_themes=1, phases_per_theme=1, tasks_per_phase=1)
    phases[0].status = "已暂停"
    phases[0].activated_at = _YESTERDAY
    from app.models.task import Task

    task = db_session.query(Task).filter_by(phase_id=phases[0].id).one()
    db_session.flush()

    with pytest.raises(BadRequestError):
        _confirm(db_session, [task.id])


def test_confirm_pre_subtasks_anchored_to_first_human_task(db_session):
    """前置锚定到第一个 human-type 任务（learning -> human）。"""
    goal, themes, phases = make_tree(db_session, n_themes=1, phases_per_theme=1, tasks_per_phase=2)
    _activate_phase(phases[0])
    from app.models.task import Task

    tasks = db_session.query(Task).filter_by(phase_id=phases[0].id).all()
    db_session.flush()

    _confirm(db_session, [tasks[0].id, tasks[1].id], [PreSubtaskInput(name="前置1")])

    subs = db_session.query(Subtask).all()
    assert len(subs) == 1
    assert subs[0].task_id == tasks[0].id  # 第一个 human task


def test_confirm_pre_subtasks_no_human_task_not_stored(db_session):
    """无 human-type 任务 -> 前置不落库（pre_subtask_count=0）。"""
    goal, themes, phases = make_tree(db_session, n_themes=1, phases_per_theme=1, tasks_per_phase=1)
    themes[0].type = "dev"  # agent type
    _activate_phase(phases[0])
    from app.models.task import Task

    task = db_session.query(Task).filter_by(phase_id=phases[0].id).one()
    db_session.flush()

    data = _confirm(db_session, [task.id], [PreSubtaskInput(name="前置1")])

    assert data.pre_subtask_count == 0
    assert db_session.query(Subtask).count() == 0
    # 但仍 async_triggered（agent 任务）
    assert data.async_triggered is True


def test_confirm_agent_task_triggers_async(db_session):
    """dev/survey 类型任务 -> async_triggered=true（agent serve）。"""
    goal, themes, phases = make_tree(db_session, n_themes=1, phases_per_theme=1, tasks_per_phase=1)
    themes[0].type = "survey"
    _activate_phase(phases[0])
    from app.models.task import Task

    task = db_session.query(Task).filter_by(phase_id=phases[0].id).one()
    db_session.flush()

    data = _confirm(db_session, [task.id])
    assert data.async_triggered is True
    assert data.pre_subtask_count == 0


def test_confirm_no_pre_subtasks_no_agent_no_async(db_session):
    """无前置 + 无 agent 任务 -> async_triggered=false。"""
    goal, themes, phases = make_tree(db_session, n_themes=1, phases_per_theme=1, tasks_per_phase=1)
    _activate_phase(phases[0])
    from app.models.task import Task

    task = db_session.query(Task).filter_by(phase_id=phases[0].id).one()
    db_session.flush()

    data = _confirm(db_session, [task.id])
    assert data.async_triggered is False
    assert data.pre_subtask_count == 0


def test_confirm_subtask_sort_order_increments(db_session):
    """多次 confirm 不同日 -> subtask sort_order 递增（同一 anchor task）。"""
    goal, themes, phases = make_tree(db_session, n_themes=1, phases_per_theme=1, tasks_per_phase=1)
    _activate_phase(phases[0])
    from app.models.task import Task

    task = db_session.query(Task).filter_by(phase_id=phases[0].id).one()
    db_session.flush()

    # Day 1
    _confirm(db_session, [task.id], [PreSubtaskInput(name="前置A")], date_=_TODAY)
    # Day 2
    _confirm(
        db_session,
        [task.id],
        [PreSubtaskInput(name="前置B")],
        date_=_TODAY + timedelta(days=1),
    )

    subs = db_session.query(Subtask).order_by(Subtask.sort_order).all()
    assert len(subs) == 2
    assert subs[0].sort_order == 1
    assert subs[1].sort_order == 2


def test_confirm_does_not_set_is_confirmed_then_summary_succeeds(db_session):
    """S3 confirm 后 is_confirmed=False，S5 confirm_summary 能成功（不 409）。

    回归 #12：S3 误设 is_confirmed=True 导致 S5 永远 409。
    """
    goal, themes, phases = make_tree(db_session, n_themes=1, phases_per_theme=1, tasks_per_phase=1)
    _activate_phase(phases[0])
    from app.models.task import Task

    task = db_session.query(Task).filter_by(phase_id=phases[0].id).one()
    db_session.flush()

    # S3 confirm
    data = _confirm(db_session, [task.id])
    assert data.task_count == 1

    # S3 后 is_confirmed=False（默认，S5 才置 true）
    dr = db_session.query(DailyRecord).one()
    assert dr.is_confirmed is False
    assert dr.confirmed_at is None

    # S5 confirm_summary 能成功（不 409）
    summary = DailyAppSvc(db_session).confirm_summary(data.daily_id)
    assert summary.confirmed is True

    # S5 后 is_confirmed=True
    db_session.flush()
    assert dr.is_confirmed is True
    assert dr.confirmed_at is not None


# ===== opencode 桩调用验证 =====


def test_trigger_async_calls_opencode_stubs(db_session, monkeypatch):
    """trigger_async（独立 session）调 opencode dispatch_pre_subtasks 桩。"""
    from sqlalchemy.orm import sessionmaker

    from app.services import daily_app_svc

    goal, themes, phases = make_tree(db_session, n_themes=1, phases_per_theme=1, tasks_per_phase=1)
    _activate_phase(phases[0])
    from app.models.task import Task

    task = db_session.query(Task).filter_by(phase_id=phases[0].id).one()
    db_session.flush()

    data = _confirm(db_session, [task.id], [PreSubtaskInput(name="前置1")])
    db_session.flush()

    # monkeypatch SessionLocal -> 测试 engine
    monkeypatch.setattr(
        daily_app_svc,
        "SessionLocal",
        sessionmaker(bind=db_session.bind, expire_on_commit=False),
    )

    calls = []

    def _capture(subs):
        calls.append(subs)

    with patch.object(daily_app_svc.OpenCodeClient, "dispatch_pre_subtasks", side_effect=_capture):
        DailyAppSvc.trigger_async(data.daily_id)

    assert len(calls) == 1
    assert len(calls[0]) == 1
    assert calls[0][0]["name"] == "前置1"


def test_trigger_async_dispatches_agent_main_task(db_session, monkeypatch):
    """FIX-2: trigger_async 对 agent-type 任务调 start_agent_serve 且传 task 参数。

    回归：原实现只 `start_agent_serve(ws.id)` 不传 task，导致 start_agent_serve 内
    `if task:` 不满足，首个智能体主任务不被 dispatch。
    """
    from uuid import uuid4

    from sqlalchemy.orm import sessionmaker

    from app.models.workspace import Workspace
    from app.services import daily_app_svc

    goal, themes, phases = make_tree(db_session, n_themes=1, phases_per_theme=1, tasks_per_phase=2)
    themes[0].type = "dev"  # agent type
    _activate_phase(phases[0])
    # trigger_async 查 Workspace join Theme，需建 workspace 才能查到 agent 任务
    ws = Workspace(
        id=str(uuid4()),
        theme_id=themes[0].id,
        path=f"data/workspaces/{uuid4().hex[:8]}",
        managed=True,
        status="已就绪",
        type="dev",
    )
    db_session.add(ws)
    db_session.flush()

    from app.models.task import Task

    tasks = db_session.query(Task).filter_by(phase_id=phases[0].id).all()
    db_session.flush()

    data = _confirm(db_session, [tasks[0].id, tasks[1].id])
    db_session.flush()

    monkeypatch.setattr(
        daily_app_svc,
        "SessionLocal",
        sessionmaker(bind=db_session.bind, expire_on_commit=False),
    )

    serve_calls: list[tuple] = []

    def _capture_serve(workspace_id, task=None):
        serve_calls.append((workspace_id, task))

    with (
        patch.object(daily_app_svc.OpenCodeClient, "start_agent_serve", side_effect=_capture_serve),
        patch.object(daily_app_svc.OpenCodeClient, "dispatch_pre_subtasks"),
    ):
        DailyAppSvc.trigger_async(data.daily_id)

    # 2 个 agent 任务 -> start_agent_serve 调 2 次，每次带 task dict
    assert len(serve_calls) == 2
    for ws_id, task in serve_calls:
        assert ws_id == ws.id  # 同一 workspace（幂等复用）
        assert task is not None
        assert "task_id" in task
        assert "name" in task
        assert "phase_id" in task
        assert task["phase_id"] == phases[0].id
    # task_id 对应 daily 计划中的 agent 任务
    dispatched_task_ids = {c[1]["task_id"] for c in serve_calls}
    assert dispatched_task_ids == {tasks[0].id, tasks[1].id}
    # name 取自 task.name
    dispatched_names = {c[1]["name"] for c in serve_calls}
    assert dispatched_names == {tasks[0].name, tasks[1].name}


def test_trigger_async_no_agent_task_no_serve(db_session, monkeypatch):
    """FIX-2 回归：learning-type 任务（非 agent）不调 start_agent_serve。"""
    from sqlalchemy.orm import sessionmaker

    from app.services import daily_app_svc

    goal, themes, phases = make_tree(db_session, n_themes=1, phases_per_theme=1, tasks_per_phase=1)
    _activate_phase(phases[0])
    from app.models.task import Task

    task = db_session.query(Task).filter_by(phase_id=phases[0].id).one()
    db_session.flush()

    data = _confirm(db_session, [task.id])
    db_session.flush()

    monkeypatch.setattr(
        daily_app_svc,
        "SessionLocal",
        sessionmaker(bind=db_session.bind, expire_on_commit=False),
    )

    with (
        patch.object(daily_app_svc.OpenCodeClient, "start_agent_serve") as mock_serve,
        patch.object(daily_app_svc.OpenCodeClient, "dispatch_pre_subtasks"),
    ):
        DailyAppSvc.trigger_async(data.daily_id)

    mock_serve.assert_not_called()
