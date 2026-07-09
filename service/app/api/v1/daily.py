"""今日计划接口（Story3 + Story5 日终总结）。详见《服务API文档 v2.0》3.4/3.5。

Story3：
  GET  /daily/plans/pool        今日任务池预查询（只读，供 pm-daily LLM 决策）
  POST /daily/confirm            确认今日计划（任务勾选+前置勾选 -> INSERT 3 表 + 异步执行前置）

Story5：
  GET  /daily/summary/generate   日终总结统计预查询（只读，纯 Service 代码）
  POST /daily/summary/confirm    确认日终总结（标记 is_confirmed + 异步写 daily.md）
"""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.common import ApiResponse
from app.schemas.daily import (
    DailyConfirmData,
    DailyConfirmRequest,
    DailyPoolData,
    DailySummaryConfirmData,
    DailySummaryConfirmRequest,
    DailySummaryData,
)
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


# ---- Story5: 日终总结 ----


@router.get("/summary/generate", response_model=ApiResponse[DailySummaryData])
def generate_summary(
    db: DBSession,
    user_id: Annotated[str, Query()],
    date: Annotated[date | None, Query()] = None,
) -> ApiResponse[DailySummaryData]:
    """日终总结统计预查询（只读）。统计为 Service 代码，文案/建议由 pm-summary LLM。"""
    data = DailyAppSvc(db).generate_summary(user_id, date)
    return ApiResponse(data=data)


@router.post("/summary/confirm", response_model=ApiResponse[DailySummaryConfirmData])
def confirm_summary(
    payload: DailySummaryConfirmRequest, db: DBSession, background_tasks: BackgroundTasks
) -> ApiResponse[DailySummaryConfirmData]:
    """确认日终总结：标记 is_confirmed + 事务后异步写 daily.md 快照。不级联。"""
    data = DailyAppSvc(db).confirm_summary(payload.daily_id)
    # 事务后异步写 daily.md（飞书 3 秒超时内不阻塞）
    background_tasks.add_task(DailyAppSvc.write_daily_md_async, payload.daily_id)
    return ApiResponse(data=data)
