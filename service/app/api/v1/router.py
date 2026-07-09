"""API v1 路由聚合。每个子 router 对应一个业务域，详见《服务API文档 v2.0》。"""

from fastapi import APIRouter

from app.api.v1 import (
    agents,
    board,
    daily,
    drafts,
    plans,
    schedules,
    stats,
    subtask_templates,
    subtasks,
    tasks,
    weekly,
    workspaces,
)

api_router = APIRouter()

api_router.include_router(plans.router, prefix="/plans", tags=["规划"])
api_router.include_router(drafts.router, prefix="/drafts", tags=["草稿"])
api_router.include_router(schedules.router, prefix="/schedules", tags=["调度"])
api_router.include_router(tasks.router, prefix="/tasks", tags=["任务"])
api_router.include_router(daily.router, prefix="/daily", tags=["今日计划"])
api_router.include_router(weekly.router, prefix="/weekly", tags=["周总结"])
api_router.include_router(workspaces.router, prefix="/workspaces", tags=["项目空间"])
api_router.include_router(subtasks.router, prefix="/subtasks", tags=["子任务"])
api_router.include_router(
    subtask_templates.router, prefix="/subtask-templates", tags=["子任务模板"]
)
api_router.include_router(agents.router, prefix="/agents", tags=["智能体进程"])
api_router.include_router(stats.router, prefix="/stats", tags=["统计"])
api_router.include_router(board.router, prefix="/board", tags=["H5看板编辑"])
