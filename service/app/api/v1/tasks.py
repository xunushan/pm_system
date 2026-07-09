"""任务接口。详见《服务API文档 v2.0》3.5。

Story4A：
  GET  /tasks/{taskId}                    任务详情（含 executor）
  POST /tasks/{taskId}/confirm-complete   人工确认完成（即时级联，无后置）
  POST /tasks/{taskId}/output/confirm     验收通过智能体产出
  POST /tasks/{taskId}/output/reject      需要修改（重试/通知）

Story4B：
  POST /tasks/{taskId}/complete           标记完成（即时级联，不含后置）
  POST /tasks/{taskId}/post-confirm        后置确认（INSERT 后置，可全取消）

Story5：
  PATCH /tasks/{taskId}                   日终异议双向状态变更（即时级联 + 刷新卡片）

Story9：
  DELETE /tasks/{taskId}                  物理删除
  POST  /board/{entity}/{id}/status       H5 状态变更（暂停/恢复/回退，含 reason）
"""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.board import TaskDeleteData
from app.schemas.common import ApiResponse
from app.schemas.task import (
    ConfirmCompleteData,
    ConfirmCompleteRequest,
    OutputConfirmData,
    OutputConfirmRequest,
    OutputRejectData,
    OutputRejectRequest,
    PostConfirmData,
    PostConfirmRequest,
    TaskCompleteData,
    TaskCompleteRequest,
    TaskDetailData,
    TaskPatchStatusData,
    TaskPatchStatusRequest,
)
from app.services.board_app_svc import BoardAppSvc
from app.services.task_app_svc import TaskAppSvc

router = APIRouter()

DBSession = Annotated[Session, Depends(get_db)]


@router.get("/{task_id}", response_model=ApiResponse[TaskDetailData])
def get_task(task_id: str, db: DBSession) -> ApiResponse[TaskDetailData]:
    """获取任务详情（含 executor）。"""
    data = TaskAppSvc(db).get_task(task_id)
    return ApiResponse(data=data)


@router.post("/{task_id}/complete", response_model=ApiResponse[TaskCompleteData])
def complete_task(
    task_id: str, payload: TaskCompleteRequest, db: DBSession
) -> ApiResponse[TaskCompleteData]:
    """标记任务完成 + 即时级联（不含后置，完成和后置脱钩）。

    pm-subtask 内部调用（4B 人完成任务时）。
    """
    data = TaskAppSvc(db).complete(task_id, payload.user_id)
    return ApiResponse(data=data)


@router.post("/{task_id}/post-confirm", response_model=ApiResponse[PostConfirmData])
def post_confirm(
    task_id: str,
    payload: PostConfirmRequest,
    db: DBSession,
    background_tasks: BackgroundTasks,
) -> ApiResponse[PostConfirmData]:
    """后置确认：INSERT 勾选的后置子任务（可全取消），事务后异步执行。

    全取消（post_subtasks 为空）-> 不插入，任务仍已完成。
    """
    data = TaskAppSvc(db).post_confirm(task_id, payload.user_id, payload.post_subtasks)
    # 事务后异步：opencode run 执行后置（飞书 3 秒超时内不阻塞）
    if data.async_triggered:
        background_tasks.add_task(TaskAppSvc.trigger_post_async, task_id)
    return ApiResponse(data=data)


@router.post("/{task_id}/confirm-complete", response_model=ApiResponse[ConfirmCompleteData])
def confirm_complete(
    task_id: str, payload: ConfirmCompleteRequest, db: DBSession
) -> ApiResponse[ConfirmCompleteData]:
    """4A 人工确认完成。3 次重试不通过，用户手动接管后调用。即时级联，无后置。"""
    data = TaskAppSvc(db).confirm_complete(task_id, payload.user_id)
    return ApiResponse(data=data)


@router.post("/{task_id}/output/confirm", response_model=ApiResponse[OutputConfirmData])
def output_confirm(
    task_id: str, payload: OutputConfirmRequest, db: DBSession
) -> ApiResponse[OutputConfirmData]:
    """验收通过智能体产出。即时级联。"""
    data = TaskAppSvc(db).output_confirm(task_id, payload.user_id, payload.workspace_progress_ids)
    return ApiResponse(data=data)


@router.post("/{task_id}/output/reject", response_model=ApiResponse[OutputRejectData])
def output_reject(
    task_id: str,
    payload: OutputRejectRequest,
    db: DBSession,
    background_tasks: BackgroundTasks,
) -> ApiResponse[OutputRejectData]:
    """退回智能体产出，重试或通知。

    事务内仅更新 retry_count（飞书 3 秒超时内不阻塞）；
    事务后异步触发 dispatch_task/shutdown/飞书通知。
    """
    data = TaskAppSvc(db).output_reject(task_id, payload.user_id, payload.feedback)
    # 事务后异步：retry 的 dispatch_task + Redis / manual_intervention 的 shutdown + 通知
    background_tasks.add_task(TaskAppSvc.trigger_reject_async, task_id, payload.feedback)
    return ApiResponse(data=data)


# ---- Story5: 日终异议双向 PATCH ----


@router.patch("/{task_id}", response_model=ApiResponse[TaskPatchStatusData])
def patch_task_status(
    task_id: str,
    payload: TaskPatchStatusRequest,
    db: DBSession,
) -> ApiResponse[TaskPatchStatusData]:
    """日终异议双向状态变更：待执行↔已完成。

    触发即时级联（forward 完成级联 / revert 回退级联）。
    revert 由系统自动填默认 reason（D18 裁决：不弹窗）。
    事务后异步刷卡片由 webhook 层 BackgroundTasks 负责（API 层不需要）。
    """
    data = TaskAppSvc(db).patch_status(
        task_id=task_id,
        status=payload.status,
        triggered_by=payload.triggered_by,
        completed_at=payload.completed_at,
    )
    return ApiResponse(data=data)


# ---- Story9: 物理删除任务 DELETE ----


@router.delete("/{task_id}", response_model=ApiResponse[TaskDeleteData])
def delete_task(task_id: str, db: DBSession) -> ApiResponse[TaskDeleteData]:
    """物理删除任务（H5 页面操作，doc/04 line 534）。

    删除关联记录（daily_tasks/subtasks/workspace_progress）后物理删除 task。
    不触发完成级联（物理删除是结构调整，非完成动作）。
    """
    data = BoardAppSvc(db).delete_task(task_id)
    return ApiResponse(data=data)
