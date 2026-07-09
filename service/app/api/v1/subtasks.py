"""子任务接口（Story4B）。详见《服务API文档 v2.0》子任务节。

前置/后置只服务人执行任务，智能体执行（opencode run）。
后置和完成脱钩：完成即时级联，后置可选收尾，可全取消。

S3 已建 subtasks 表 + 前置 INSERT（confirm 时落库）；subtasks 路由 CRUD 留 S4B。
"""

from fastapi import APIRouter

router = APIRouter()


@router.get("/")
def list_subtasks() -> dict:
    """TODO(Story4B)。"""
    return {"todo": "implement Story4B - 见 doc/04 子任务节"}
