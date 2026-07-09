"""统计接口（Story5/Story6，doc/04 统计节）。

GET /api/v1/stats/daily    获取日统计（日终/周总结共用统计查询核心）
GET /api/v1/stats/weekly   获取周统计（同 weekly/summary/generate data）

纯查询，无 LLM，无副作用。pm-summary Skill 调用本组接口获取统计数据，
文案与建议由 LLM 生成（Service 不调 LLM，铁律 §3#1）。
"""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.common import ApiResponse
from app.schemas.stats import DailyStatsData
from app.schemas.weekly import WeeklyStatsData
from app.services.stats_app_svc import StatsAppSvc

router = APIRouter()

DBSession = Annotated[Session, Depends(get_db)]


@router.get("/daily", response_model=ApiResponse[DailyStatsData])
def get_daily_stats(
    db: DBSession,
    user_id: Annotated[str, Query()],
    date: Annotated[date | None, Query()] = None,
) -> ApiResponse[DailyStatsData]:
    """获取日统计（日终/周总结共用统计查询核心）。只读。"""
    data = StatsAppSvc(db).get_daily_stats(user_id, date)
    return ApiResponse(data=data)


@router.get("/weekly", response_model=ApiResponse[WeeklyStatsData])
def get_weekly_stats(
    db: DBSession,
    user_id: Annotated[str, Query()],
    week: Annotated[str, Query()],
) -> ApiResponse[WeeklyStatsData]:
    """获取周统计（同 weekly/summary/generate data，doc/04 3.11）。只读。"""
    data = StatsAppSvc(db).get_weekly_stats(user_id, week)
    return ApiResponse(data=data)
