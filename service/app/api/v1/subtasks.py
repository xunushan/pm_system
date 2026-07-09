"""子任务接口。详见《服务API文档 v2.0》3.9。

前置/后置只服务人执行任务，智能体执行（opencode run）。
后置和完成脱钩：完成即时级联，后置可选收尾，可全取消。

POST   /subtasks             创建子任务（前置/后置，由 pm-subtask 生成后调用）
GET    /subtasks/{subtaskId}  获取子任务详情
PATCH  /subtasks/{subtaskId}  更新子任务状态（异步执行完成后回调）
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.common import ApiResponse
from app.schemas.subtask import SubtaskCreateRequest, SubtaskData, SubtaskPatchRequest
from app.services.task_app_svc import TaskAppSvc

router = APIRouter()

DBSession = Annotated[Session, Depends(get_db)]


@router.post("", response_model=ApiResponse[SubtaskData])
def create_subtask(payload: SubtaskCreateRequest, db: DBSession) -> ApiResponse[SubtaskData]:
    """创建子任务（前置/后置，由 pm-subtask 生成后调用）。"""
    data = TaskAppSvc(db).create_subtask(payload)
    return ApiResponse(data=data)


@router.get("/{subtask_id}", response_model=ApiResponse[SubtaskData])
def get_subtask(subtask_id: str, db: DBSession) -> ApiResponse[SubtaskData]:
    """获取子任务详情。"""
    data = TaskAppSvc(db).get_subtask(subtask_id)
    return ApiResponse(data=data)


@router.patch("/{subtask_id}", response_model=ApiResponse[SubtaskData])
def patch_subtask(
    subtask_id: str, payload: SubtaskPatchRequest, db: DBSession
) -> ApiResponse[SubtaskData]:
    """更新子任务状态（异步执行完成后回调）。"""
    data = TaskAppSvc(db).patch_subtask(subtask_id, payload)
    return ApiResponse(data=data)
