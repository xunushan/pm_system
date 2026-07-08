"""今日计划接口（Story3）。详见《服务API文档 v2.0》今日计划节。

POST /daily/confirm   勾选任务 + 前置 -> INSERT daily_records/daily_tasks/subtasks + 异步执行前置
GET  /daily/today     查今日计划（push_source 区分 auto/manual）
"""

from fastapi import APIRouter

router = APIRouter()


@router.get("/")
def list_daily() -> dict:
    """TODO(Story3)。"""
    return {"todo": "implement Story3 - 见 doc/04 今日计划节"}
