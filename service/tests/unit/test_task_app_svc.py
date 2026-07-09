"""TaskAppSvc 单元测试：complete + post_confirm + subtask CRUD（Story4B）。

验证要点：
  - complete：标记完成 + 即时级联 + 审计（forward）
  - complete：已完成 -> 409 ConflictError；已暂停 -> 400 BadRequestError；不存在 -> 404
  - post_confirm：INSERT 后置 + 全取消不插入 + task 未完成拒绝 + 非 human executor 拒绝
  - subtask CRUD
"""

import pytest

from app.core.exceptions import BadRequestError, ConflictError, NotFoundError
from app.models.status_change_log import StatusChangeLog
from app.models.subtask import Subtask
from app.models.task import Task
from app.schemas.subtask import SubtaskCreateRequest, SubtaskPatchRequest
from app.schemas.task import PostSubtaskInput
from app.services.task_app_svc import TaskAppSvc
from tests._factory import make_tree


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


# ===== complete =====


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


# ===== post_confirm =====


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


# ===== subtask CRUD =====


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
