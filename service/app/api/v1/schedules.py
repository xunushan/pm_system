"""调度激活接口（Story2 + Story8）。详见《服务API文档 v2.0》3.3。

patch 卡片形式：卡片 A 多选专题 + 设 managed/path；卡片 B 填各阶段 deadline。
  POST /schedules/confirm   多选专题+managed/path+deadline -> 激活+即时级联+异步初始化
  POST /schedules/activate   阶段衔接激活（Story8，Supervisor 推卡片后用户确认）
"""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.common import ApiResponse
from app.schemas.schedule import (
    ScheduleActivateData,
    ScheduleActivateRequest,
    ScheduleConfirmData,
    ScheduleConfirmRequest,
)
from app.services.schedule_app_svc import ScheduleAppSvc
from app.services.workspace_app_svc import WorkspaceAppSvc

router = APIRouter()

DBSession = Annotated[Session, Depends(get_db)]


@router.post("/confirm", response_model=ApiResponse[ScheduleConfirmData])
def confirm_schedule(
    payload: ScheduleConfirmRequest, db: DBSession, background_tasks: BackgroundTasks
) -> ApiResponse[ScheduleConfirmData]:
    """确认调度：事务内激活+级联+审计，事务后异步初始化 managed=1 工作空间。"""
    data = ScheduleAppSvc(db).confirm(payload.user_id, payload.goal_id, payload.items)
    # 事务后异步：managed=1 工作空间初始化（mkdir+git init+骨架），managed=0 已就绪无需异步
    for ap in data.activated_phases:
        if ap.workspace_managed:
            background_tasks.add_task(WorkspaceAppSvc.init, ap.workspace_id)
    return ApiResponse(data=data)


@router.post("/activate", response_model=ApiResponse[ScheduleActivateData])
def activate_phase(
    payload: ScheduleActivateRequest, db: DBSession, background_tasks: BackgroundTasks
) -> ApiResponse[ScheduleActivateData]:
    """阶段衔接激活（Story8）：Supervisor 推衔接卡片后用户确认激活下阶段。

    事务内：UPDATE phase(进行中,activated_at,deadline) + 即时级联 + audit(forward,supervisor)。
    事务后异步：managed=1 工作空间初始化（新建 workspace 时）。满足飞书 3 秒回调（铁律 #4）。
    """
    data = ScheduleAppSvc(db).activate(payload.phase_id, payload.deadline, payload.user_id)
    # 事务后异步：managed=1 且未初始化的工作空间初始化（3 秒超时内不阻塞）
    if data.workspace_managed and data.workspace_status == "未初始化":
        background_tasks.add_task(WorkspaceAppSvc.init, data.workspace_id)
    return ApiResponse(data=data)
