"""调度激活接口（Story2）。详见《服务API文档 v2.0》3.3。

patch 卡片形式：卡片 A 多选专题 + 设 managed/path；卡片 B 填各阶段 deadline。
  POST /schedules/confirm   多选专题+managed/path+deadline -> 激活+即时级联+异步初始化
"""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.common import ApiResponse
from app.schemas.schedule import ScheduleConfirmData, ScheduleConfirmRequest
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
