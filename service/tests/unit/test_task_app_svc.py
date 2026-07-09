"""TaskAppSvc 单元测试：Story4A + Story4B 方法。

Story4B 测试：complete + post_confirm + subtask CRUD
  - complete：标记完成 + 即时级联 + 审计（forward）
  - complete：已完成 -> 409 ConflictError；已暂停 -> 400 BadRequestError；不存在 -> 404
  - post_confirm：INSERT 后置 + 全取消不插入 + task 未完成拒绝 + 非 human executor 拒绝
  - subtask CRUD

Story4A 测试：confirm_complete + output_confirm + output_reject + record_output + handle_timeout
  - mock cascade/state_machine/opencode/feishu/redis
"""

from datetime import date
from unittest.mock import patch
from uuid import uuid4

import pytest

from app.core.exceptions import BadRequestError, ConflictError, NotFoundError
from app.models.agent_process import AgentProcess
from app.models.status_change_log import StatusChangeLog
from app.models.subtask import Subtask
from app.models.task import Task
from app.models.workspace import Workspace
from app.schemas.subtask import SubtaskCreateRequest, SubtaskPatchRequest
from app.schemas.task import PostSubtaskInput
from app.services import task_app_svc
from app.services.task_app_svc import TaskAppSvc
from tests._factory import make_tree

_TODAY = date(2026, 7, 9)


# ===== Story4B: 测试辅助 =====


def _setup_active_task(db_session, *, executor="human", tasks_per_phase=1):
    """建树 + 激活 phase/theme/goal + 返回 task（待执行）。"""
    goal, themes, phases = make_tree(db_session, tasks_per_phase=tasks_per_phase)
    goal.status = "进行中"
    themes[0].status = "进行中"
    phases[0].status = "进行中"
    task = (
        db_session.query(Task)
        .filter(Task.phase_id == phases[0].id)
        .order_by(Task.sort_order)
        .first()
    )
    task.executor = executor
    db_session.flush()
    return goal, themes, phases, task


# ===== Story4A: 测试辅助 =====


def _make_full_tree(db, *, theme_type="dev", task_executor=None):
    """建 goal->theme->phase->task + workspace 树。

    theme_type='dev' -> executor='agent'（智能体任务）。
    """
    goal, themes, phases = make_tree(db, n_themes=1, phases_per_theme=1, tasks_per_phase=2)
    themes[0].type = theme_type
    # 激活 phase
    phases[0].status = "进行中"
    phases[0].activated_at = _TODAY
    # 创建 workspace
    ws = Workspace(
        id=str(uuid4()),
        theme_id=themes[0].id,
        path=f"data/workspaces/{uuid4().hex[:8]}",
        managed=True,
        status="已就绪",
        type=theme_type,
    )
    db.add(ws)
    db.flush()
    # 设置 task executor
    tasks = db.query(Task).filter_by(phase_id=phases[0].id).all()
    for t in tasks:
        t.executor = task_executor
    db.flush()
    return goal, themes, phases, ws, tasks


# ===== Story4B: complete =====


def test_complete_marks_task_and_cascades(db_session):
    """complete：标记完成 + 级联 phase 完成 + 写 forward 审计。"""
    goal, themes, phases, task = _setup_active_task(db_session)
    svc = TaskAppSvc(db_session)

    data = svc.complete(task.id, "user_001")

    assert data.task_id == task.id
    assert data.status == "已完成"
    assert data.cascade.phase_completed is True
    assert data.cascade.theme_completed is True
    assert data.cascade.goal_completed is True

    db_session.flush()
    assert task.status == "已完成"
    assert task.completed_at is not None

    # forward 审计（task）
    forward_logs = (
        db_session.query(StatusChangeLog).filter_by(entity_type="task", change_type="forward").all()
    )
    assert len(forward_logs) == 1
    assert forward_logs[0].triggered_by == "user"
    assert forward_logs[0].from_status == "待执行"
    assert forward_logs[0].to_status == "已完成"


def test_complete_already_completed_raises_conflict(db_session):
    """已完成任务再 complete -> ConflictError (409)。"""
    goal, themes, phases, task = _setup_active_task(db_session)
    task.status = "已完成"
    db_session.flush()

    with pytest.raises(ConflictError):
        TaskAppSvc(db_session).complete(task.id, "user_001")


def test_complete_paused_task_raises_bad_request(db_session):
    """已暂停任务 complete -> BadRequestError (400)。"""
    goal, themes, phases, task = _setup_active_task(db_session)
    task.status = "已暂停"
    db_session.flush()

    with pytest.raises(BadRequestError):
        TaskAppSvc(db_session).complete(task.id, "user_001")


def test_complete_not_found_raises(db_session):
    """不存在的 task -> NotFoundError (404)。"""
    with pytest.raises(NotFoundError):
        TaskAppSvc(db_session).complete("no-such-id", "user_001")


def test_complete_does_not_cascade_when_tasks_pending(db_session):
    """phase 下有多 task，完成 1 个不触发 phase 完成。"""
    goal, themes, phases, task = _setup_active_task(db_session, tasks_per_phase=2)
    svc = TaskAppSvc(db_session)

    data = svc.complete(task.id, "user_001")

    assert data.cascade.phase_completed is False
    assert data.cascade.theme_completed is False
    assert data.cascade.goal_completed is False
    db_session.flush()
    assert phases[0].status == "进行中"


# ===== Story4B: post_confirm =====


def test_post_confirm_inserts_post_subtasks(db_session):
    """post_confirm：INSERT 勾选的后置子任务。"""
    goal, themes, phases, task = _setup_active_task(db_session)
    task.status = "已完成"
    db_session.flush()

    data = TaskAppSvc(db_session).post_confirm(
        task.id,
        "user_001",
        [
            PostSubtaskInput(name="笔记归档"),
            PostSubtaskInput(name="自测题生成"),
        ],
    )

    assert data.task_id == task.id
    assert data.post_subtask_count == 2
    assert data.async_triggered is True

    subs = db_session.query(Subtask).filter_by(task_id=task.id, type="后置").all()
    assert len(subs) == 2
    assert subs[0].name == "笔记归档"
    assert subs[0].status == "待执行"
    assert subs[1].name == "自测题生成"
    assert subs[1].sort_order == 2


def test_post_confirm_empty_list_no_insert(db_session):
    """post_confirm：全取消（空列表）-> 不插入后置，async_triggered=False。"""
    goal, themes, phases, task = _setup_active_task(db_session)
    task.status = "已完成"
    db_session.flush()

    data = TaskAppSvc(db_session).post_confirm(task.id, "user_001", [])

    assert data.post_subtask_count == 0
    assert data.async_triggered is False
    assert db_session.query(Subtask).filter_by(task_id=task.id).count() == 0


def test_post_confirm_task_not_completed_rejects(db_session):
    """post_confirm：task 未完成 -> BadRequestError。"""
    goal, themes, phases, task = _setup_active_task(db_session)
    # task.status 仍为待执行
    with pytest.raises(BadRequestError):
        TaskAppSvc(db_session).post_confirm(task.id, "user_001", [PostSubtaskInput(name="x")])


def test_post_confirm_non_human_executor_rejects(db_session):
    """post_confirm：executor 非 human -> BadRequestError（后置只对人执行任务）。"""
    goal, themes, phases, task = _setup_active_task(db_session, executor="agent")
    task.status = "已完成"
    db_session.flush()

    with pytest.raises(BadRequestError):
        TaskAppSvc(db_session).post_confirm(task.id, "user_001", [PostSubtaskInput(name="x")])


def test_post_confirm_not_found_raises(db_session):
    """post_confirm：task 不存在 -> NotFoundError。"""
    with pytest.raises(NotFoundError):
        TaskAppSvc(db_session).post_confirm("no-such-id", "user_001", [])


def test_post_confirm_appends_to_existing_subtasks(db_session):
    """post_confirm：已有前置子任务时，后置 sort_order 从已有最大值+1 起。"""
    goal, themes, phases, task = _setup_active_task(db_session)
    task.status = "已完成"
    # 已有 1 个前置子任务
    db_session.add(
        Subtask(
            id="existing-pre",
            task_id=task.id,
            sort_order=1,
            name="前置1",
            type="前置",
            status="待执行",
        )
    )
    db_session.flush()

    data = TaskAppSvc(db_session).post_confirm(
        task.id, "user_001", [PostSubtaskInput(name="后置1")]
    )

    assert data.post_subtask_count == 1
    post_subs = db_session.query(Subtask).filter_by(task_id=task.id, type="后置").all()
    assert len(post_subs) == 1
    assert post_subs[0].sort_order == 2  # 接在已有 sort_order=1 之后


# ===== Story4B: subtask CRUD =====


def test_create_subtask(db_session):
    """create_subtask：创建子任务，sort_order 自动分配。"""
    goal, themes, phases, task = _setup_active_task(db_session)
    svc = TaskAppSvc(db_session)

    data = svc.create_subtask(SubtaskCreateRequest(task_id=task.id, name="前置1", type="前置"))

    assert data.task_id == task.id
    assert data.name == "前置1"
    assert data.type == "前置"
    assert data.status == "待执行"
    assert data.sort_order == 1


def test_create_subtask_invalid_type(db_session):
    """create_subtask：非法 type -> BadRequestError。"""
    goal, themes, phases, task = _setup_active_task(db_session)
    with pytest.raises(BadRequestError):
        TaskAppSvc(db_session).create_subtask(
            SubtaskCreateRequest(task_id=task.id, name="x", type="无效")
        )


def test_create_subtask_non_human_executor_rejects(db_session):
    """create_subtask：executor 非 human -> BadRequestError（前置/后置只服务人执行任务）。"""
    goal, themes, phases, task = _setup_active_task(db_session, executor="agent")
    with pytest.raises(BadRequestError):
        TaskAppSvc(db_session).create_subtask(
            SubtaskCreateRequest(task_id=task.id, name="x", type="前置")
        )


def test_create_subtask_task_not_found(db_session):
    with pytest.raises(NotFoundError):
        TaskAppSvc(db_session).create_subtask(
            SubtaskCreateRequest(task_id="no-such-id", name="x", type="前置")
        )


def test_get_subtask(db_session):
    """get_subtask：获取子任务详情。"""
    goal, themes, phases, task = _setup_active_task(db_session)
    svc = TaskAppSvc(db_session)
    created = svc.create_subtask(SubtaskCreateRequest(task_id=task.id, name="后置1", type="后置"))

    data = svc.get_subtask(created.subtask_id)

    assert data.subtask_id == created.subtask_id
    assert data.name == "后置1"


def test_get_subtask_not_found(db_session):
    with pytest.raises(NotFoundError):
        TaskAppSvc(db_session).get_subtask("no-such-id")


def test_patch_subtask_status(db_session):
    """patch_subtask：更新状态 + completed_at。"""
    goal, themes, phases, task = _setup_active_task(db_session)
    svc = TaskAppSvc(db_session)
    created = svc.create_subtask(SubtaskCreateRequest(task_id=task.id, name="后置1", type="后置"))

    data = svc.patch_subtask(
        created.subtask_id, SubtaskPatchRequest(status="已完成", output_path="/out/path")
    )

    assert data.status == "已完成"
    assert data.output_path == "/out/path"
    assert data.completed_at is not None


def test_patch_subtask_invalid_status(db_session):
    """patch_subtask：非法状态 -> BadRequestError。"""
    goal, themes, phases, task = _setup_active_task(db_session)
    svc = TaskAppSvc(db_session)
    created = svc.create_subtask(SubtaskCreateRequest(task_id=task.id, name="x", type="前置"))

    with pytest.raises(BadRequestError):
        svc.patch_subtask(created.subtask_id, SubtaskPatchRequest(status="无效"))


def test_patch_subtask_not_found(db_session):
    with pytest.raises(NotFoundError):
        TaskAppSvc(db_session).patch_subtask("no-such-id", SubtaskPatchRequest(status="已完成"))


# ===== patch_subtask 状态流转校验（P2-2）=====


def test_patch_subtask_forward_transitions_ok(db_session):
    """patch_subtask：正向流转待执行->进行中->已完成 允许。"""
    goal, themes, phases, task = _setup_active_task(db_session)
    svc = TaskAppSvc(db_session)
    created = svc.create_subtask(SubtaskCreateRequest(task_id=task.id, name="x", type="前置"))

    # 待执行 -> 进行中
    data = svc.patch_subtask(created.subtask_id, SubtaskPatchRequest(status="进行中"))
    assert data.status == "进行中"

    # 进行中 -> 已完成
    data = svc.patch_subtask(created.subtask_id, SubtaskPatchRequest(status="已完成"))
    assert data.status == "已完成"
    assert data.completed_at is not None


def test_patch_subtask_to_failed_ok(db_session):
    """patch_subtask：待执行->失败 / 进行中->失败 允许。"""
    goal, themes, phases, task = _setup_active_task(db_session)
    svc = TaskAppSvc(db_session)
    created = svc.create_subtask(SubtaskCreateRequest(task_id=task.id, name="x", type="前置"))

    data = svc.patch_subtask(created.subtask_id, SubtaskPatchRequest(status="失败"))
    assert data.status == "失败"


def test_patch_subtask_completed_to_pending_rejects(db_session):
    """patch_subtask：已完成->待执行 逆向流转 -> BadRequestError。"""
    goal, themes, phases, task = _setup_active_task(db_session)
    svc = TaskAppSvc(db_session)
    created = svc.create_subtask(SubtaskCreateRequest(task_id=task.id, name="x", type="前置"))
    svc.patch_subtask(created.subtask_id, SubtaskPatchRequest(status="已完成"))

    with pytest.raises(BadRequestError):
        svc.patch_subtask(created.subtask_id, SubtaskPatchRequest(status="待执行"))


def test_patch_subtask_failed_to_pending_rejects(db_session):
    """patch_subtask：失败->待执行 逆向流转 -> BadRequestError。"""
    goal, themes, phases, task = _setup_active_task(db_session)
    svc = TaskAppSvc(db_session)
    created = svc.create_subtask(SubtaskCreateRequest(task_id=task.id, name="x", type="前置"))
    svc.patch_subtask(created.subtask_id, SubtaskPatchRequest(status="失败"))

    with pytest.raises(BadRequestError):
        svc.patch_subtask(created.subtask_id, SubtaskPatchRequest(status="待执行"))


def test_patch_subtask_in_progress_to_pending_rejects(db_session):
    """patch_subtask：进行中->待执行 逆向流转 -> BadRequestError。"""
    goal, themes, phases, task = _setup_active_task(db_session)
    svc = TaskAppSvc(db_session)
    created = svc.create_subtask(SubtaskCreateRequest(task_id=task.id, name="x", type="前置"))
    svc.patch_subtask(created.subtask_id, SubtaskPatchRequest(status="进行中"))

    with pytest.raises(BadRequestError):
        svc.patch_subtask(created.subtask_id, SubtaskPatchRequest(status="待执行"))


# ===== Story4A: confirm_complete =====


def test_confirm_complete_marks_task_done(db_session):
    """confirm_complete 标记任务完成 + 审计 + 级联。"""
    goal, themes, phases, ws, tasks = _make_full_tree(db_session, task_executor="agent")
    task = tasks[0]

    with (
        patch.object(task_app_svc.state_machine, "validate_transition"),
        patch.object(task_app_svc.cascade, "cascade_status"),
        patch.object(task_app_svc, "emit"),
        patch.object(task_app_svc.OpenCodeClient, "shutdown"),
        patch.object(task_app_svc.OpenCodeClient, "start_agent_serve", return_value=10001),
    ):
        svc = task_app_svc.TaskAppSvc(db_session)
        data = svc.confirm_complete(task.id, "user_001")

    assert data.status == "已完成"
    assert data.task_id == task.id
    db_session.refresh(task)
    assert task.status == "已完成"
    assert task.completed_at is not None


def test_confirm_complete_not_found(db_session):
    """任务不存在 -> 404。"""
    from app.core.exceptions import NotFoundError

    svc = task_app_svc.TaskAppSvc(db_session)
    with pytest.raises(NotFoundError):
        svc.confirm_complete("nonexistent", "u1")


def test_confirm_complete_already_done(db_session):
    """任务已完成 -> 400。"""
    from app.core.exceptions import BadRequestError

    goal, themes, phases, ws, tasks = _make_full_tree(db_session, task_executor="agent")
    tasks[0].status = "已完成"
    db_session.flush()

    svc = task_app_svc.TaskAppSvc(db_session)
    with pytest.raises(BadRequestError):
        svc.confirm_complete(tasks[0].id, "u1")


def test_confirm_complete_restarts_opencode_when_next_agent_task(
    db_session,
):
    """有后续智能体任务 -> 重启 opencode serve。"""
    goal, themes, phases, ws, tasks = _make_full_tree(db_session, task_executor="agent")
    task = tasks[0]
    next_task = tasks[1]
    next_task.status = "待执行"
    next_task.executor = "agent"
    db_session.flush()

    with (
        patch.object(task_app_svc.state_machine, "validate_transition"),
        patch.object(task_app_svc.cascade, "cascade_status"),
        patch.object(task_app_svc, "emit"),
        patch.object(task_app_svc.OpenCodeClient, "shutdown") as mock_shutdown,
        patch.object(
            task_app_svc.OpenCodeClient, "start_agent_serve", return_value=10002
        ) as mock_start,
    ):
        svc = task_app_svc.TaskAppSvc(db_session)
        data = svc.confirm_complete(task.id, "u1")

    assert data.opencode_restarted is True
    assert data.next_agent_task == next_task.id
    mock_shutdown.assert_called_once()
    mock_start.assert_called_once()


def test_confirm_complete_no_restart_when_no_next_agent(db_session):
    """无后续智能体任务 -> 不重启 opencode。"""
    goal, themes, phases, ws, tasks = _make_full_tree(db_session, task_executor="human")
    task = tasks[0]

    with (
        patch.object(task_app_svc.state_machine, "validate_transition"),
        patch.object(task_app_svc.cascade, "cascade_status"),
        patch.object(task_app_svc, "emit"),
        patch.object(task_app_svc.OpenCodeClient, "shutdown"),
        patch.object(task_app_svc.OpenCodeClient, "start_agent_serve") as mock_start,
    ):
        svc = task_app_svc.TaskAppSvc(db_session)
        data = svc.confirm_complete(task.id, "u1")

    assert data.opencode_restarted is False
    assert data.next_agent_task is None
    mock_start.assert_not_called()


# ===== Story4A: output_confirm =====


def test_output_confirm_marks_task_and_pre_subtasks_done(db_session):
    """output_confirm 标记任务完成 + 前置子任务完成 + 级联。"""
    goal, themes, phases, ws, tasks = _make_full_tree(db_session, task_executor="agent")
    task = tasks[0]
    # 添加前置子任务
    sub = Subtask(
        id=str(uuid4()),
        task_id=task.id,
        sort_order=1,
        name="前置1",
        type="前置",
        status="待执行",
    )
    db_session.add(sub)
    db_session.flush()

    with (
        patch.object(task_app_svc.state_machine, "validate_transition"),
        patch.object(task_app_svc.cascade, "cascade_status"),
        patch.object(task_app_svc, "emit"),
    ):
        svc = task_app_svc.TaskAppSvc(db_session)
        data = svc.output_confirm(task.id, "u1", [])

    assert data.status == "已完成"
    db_session.refresh(task)
    db_session.refresh(sub)
    assert task.status == "已完成"
    assert sub.status == "已完成"
    assert sub.completed_at is not None


def test_output_confirm_not_found(db_session):
    """任务不存在 -> 404。"""
    from app.core.exceptions import NotFoundError

    svc = task_app_svc.TaskAppSvc(db_session)
    with pytest.raises(NotFoundError):
        svc.output_confirm("nonexistent", "u1", [])


# ===== Story4A: output_reject =====


def test_output_reject_retry_under_limit(db_session):
    """retry_count < 3 -> 重试。"""
    goal, themes, phases, ws, tasks = _make_full_tree(db_session, task_executor="agent")
    task = tasks[0]
    task.retry_count = 1
    db_session.flush()

    # 添加 running agent_process
    ap = AgentProcess(id=str(uuid4()), workspace_id=ws.id, port=10001, status="running")
    db_session.add(ap)
    db_session.flush()

    with (
        patch.object(task_app_svc.OpenCodeClient, "dispatch_task"),
        patch.object(task_app_svc, "set_task_timeout"),
    ):
        svc = task_app_svc.TaskAppSvc(db_session)
        data = svc.output_reject(task.id, "u1", "需要修改")

    assert data.action == "retry"
    assert data.retry_count == 2
    assert data.max_retry == 3
    assert data.async_triggered is True
    db_session.refresh(task)
    assert task.status == "待执行"  # 不改状态
    assert task.retry_count == 2


def test_output_reject_at_limit_manual_intervention(db_session):
    """retry_count >= 3 -> manual_intervention。"""
    goal, themes, phases, ws, tasks = _make_full_tree(db_session, task_executor="agent")
    task = tasks[0]
    task.retry_count = 3
    db_session.flush()

    with (
        patch.object(task_app_svc.OpenCodeClient, "shutdown", return_value=True),
        patch.object(task_app_svc.FeishuClient, "send_text"),
    ):
        svc = task_app_svc.TaskAppSvc(db_session)
        data = svc.output_reject(task.id, "u1", "多次不过")

    assert data.action == "manual_intervention"
    assert data.retry_count == 3
    assert data.opencode_stopped is True
    assert data.workspace_path is not None
    db_session.refresh(task)
    assert task.status == "待执行"  # 3次不通过不改状态


def test_output_reject_not_found(db_session):
    """任务不存在 -> 404。"""
    from app.core.exceptions import NotFoundError

    svc = task_app_svc.TaskAppSvc(db_session)
    with pytest.raises(NotFoundError):
        svc.output_reject("nonexistent", "u1", "fb")


# ===== Story4A: record_output =====


def test_record_output_creates_workspace_progress(db_session):
    """record_output 记录 workspace_progress + DEL 超时 + 发卡片。"""
    goal, themes, phases, ws, tasks = _make_full_tree(db_session, task_executor="agent")
    task = tasks[0]

    outputs = [
        {"file_path": "docs/schema-v1.md", "file_type": "design"},
        {"file_path": "src/schema.py", "file_type": "code"},
    ]

    with (
        patch.object(task_app_svc, "del_task_timeout"),
        patch.object(task_app_svc.FeishuClient, "send_card"),
        patch.object(task_app_svc.FeishuClient, "send_file"),
    ):
        svc = task_app_svc.TaskAppSvc(db_session)
        data = svc.record_output(task.id, ws.id, outputs)

    assert data.received is True
    assert data.progress_count == 2

    from app.models.workspace_progress import WorkspaceProgress

    wps = db_session.query(WorkspaceProgress).filter_by(task_id=task.id).all()
    assert len(wps) == 2
    assert wps[0].file_path == "docs/schema-v1.md"
    assert wps[0].file_type == "design"


# ===== Story4A: handle_timeout =====


def test_handle_timeout_sends_alert(db_session):
    """handle_timeout 发飞书告警。"""
    with patch.object(task_app_svc.FeishuClient, "send_text") as mock_send:
        svc = task_app_svc.TaskAppSvc(db_session)
        data = svc.handle_timeout("task_001", "ws_001")

    assert data.alert_sent is True
    mock_send.assert_called_once()
