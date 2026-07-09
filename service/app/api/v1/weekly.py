"""周总结接口（Story6）。详见《服务API文档 v2.0》3.6。

GET  /weekly/summary/generate   周总结统计预查询（只读，纯 Service 代码）
POST /weekly/summary/confirm     确认周总结（标记 is_confirmed + 异步写 weekly.md）
"""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.common import ApiResponse
from app.schemas.weekly import WeeklyConfirmData, WeeklyConfirmRequest, WeeklyStatsData
from app.services.weekly_app_svc import WeeklyAppSvc

router = APIRouter()

DBSession = Annotated[Session, Depends(get_db)]


@router.get("/summary/generate", response_model=ApiResponse[WeeklyStatsData])
def generate_summary(
    db: DBSession,
    user_id: Annotated[str, Query()],
    week: Annotated[str, Query()],
) -> ApiResponse[WeeklyStatsData]:
    """周总结统计预查询（只读）。统计为 Service 代码，文案/建议由 pm-summary LLM。"""
    data = WeeklyAppSvc(db).generate_summary(user_id, week)
    return ApiResponse(data=data)


@router.post("/summary/confirm", response_model=ApiResponse[WeeklyConfirmData])
def confirm_summary(
    payload: WeeklyConfirmRequest, db: DBSession, background_tasks: BackgroundTasks
) -> ApiResponse[WeeklyConfirmData]:
    """确认周总结：INSERT/UPDATE weekly_records + 事务后异步写 weekly.md 快照。不级联。"""
    data = WeeklyAppSvc(db).confirm_summary(payload.week)
    # 事务后异步写 weekly.md（飞书 3 秒超时内不阻塞）
    background_tasks.add_task(WeeklyAppSvc.write_weekly_md_async, payload.week)
    return ApiResponse(data=data)
