"""任务接口。详见《服务API文档 v2.0》3.5。

GET   /tasks/{taskId}              获取任务详情（含 executor）
POST  /tasks/{taskId}/complete      Story4B 标记完成（即时级联，不含后置）
POST  /tasks/{taskId}/post-confirm  Story4B 后置确认（INSERT 后置，可全取消）

confirm-complete / output 端点属 Story4A，留桩 TODO。
"""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.common import ApiResponse
from app.schemas.task import (
    PostConfirmData,
    PostConfirmRequest,
    TaskCompleteData,
    TaskCompleteRequest,
    TaskDetail,
)
from app.services.task_app_svc import TaskAppSvc

router = APIRouter()

DBSession = Annotated[Session, Depends(get_db)]


@router.get("/{task_id}", response_model=ApiResponse[TaskDetail])
def get_task(task_id: str, db: DBSession) -> ApiResponse[TaskDetail]:
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


# ---- Story4A 端点留桩（confirm-complete / output）----
# POST /tasks/{taskId}/confirm-complete   Story4A 人工确认完成
# POST /tasks/{taskId}/output/confirm     Story4A 验收通过
# POST /tasks/{taskId}/output/reject       Story4A 需要修改
# TODO(Story4A): 实现上述端点，依赖本 Story 的完成级联。
