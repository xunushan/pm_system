"""今日计划接口（Story3）。详见《服务API文档 v2.0》3.4。

GET  /daily/plans/pool   今日任务池预查询（只读，供 pm-daily LLM 决策）
POST /daily/confirm       确认今日计划（任务勾选+前置勾选 -> INSERT 3 表 + 异步执行前置）
"""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.common import ApiResponse
from app.schemas.daily import DailyConfirmData, DailyConfirmRequest, DailyPoolData
from app.services.daily_app_svc import DailyAppSvc

router = APIRouter()

DBSession = Annotated[Session, Depends(get_db)]


@router.get("/plans/pool", response_model=ApiResponse[DailyPoolData])
def get_plans_pool(
    db: DBSession,
    user_id: Annotated[str, Query()],
    date: Annotated[date | None, Query()] = None,
) -> ApiResponse[DailyPoolData]:
    """今日任务池预查询（只读）。过滤已激活阶段 + 排除已暂停。"""
    data = DailyAppSvc(db).get_plans_pool(user_id, date)
    return ApiResponse(data=data)


@router.post("/confirm", response_model=ApiResponse[DailyConfirmData])
def confirm_daily(
    payload: DailyConfirmRequest, db: DBSession, background_tasks: BackgroundTasks
) -> ApiResponse[DailyConfirmData]:
    """确认今日计划：事务内 INSERT daily_records/daily_tasks/subtasks，
    事务后异步触发 opencode 执行前置 + 启动智能体 serve。
    """
    data = DailyAppSvc(db).confirm(
        user_id=payload.user_id,
        date_=payload.date,
        task_ids=payload.task_ids,
        pre_subtasks=payload.pre_subtasks,
        push_source=payload.push_source,
    )
    # 事务后异步（飞书 3 秒超时内不阻塞）
    if data.async_triggered:
        background_tasks.add_task(DailyAppSvc.trigger_async, data.daily_id)
    return ApiResponse(data=data)
