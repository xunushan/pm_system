"""子任务接口（Story4B）。详见《服务API文档 v2.0》子任务节。

前置/后置只服务人执行任务，智能体执行（opencode run）。
后置和完成脱钩：完成即时级联，后置可选收尾，可全取消。
"""

from fastapi import APIRouter

router = APIRouter()


@router.get("/")
def list_subtasks() -> dict:
    """TODO(Story4B)。"""
    return {"todo": "implement Story4B - 见 doc/04 子任务节"}
