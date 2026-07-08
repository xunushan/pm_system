"""调度激活接口（Story2）。详见《服务API文档 v2.0》调度节。

patch 卡片形式：卡片 A 多选专题 + 设 managed/path；卡片 B 填各阶段 deadline。
  POST /schedules/confirm   多选专题+managed/path+deadline -> 激活+即时级联+异步初始化
"""

from fastapi import APIRouter

router = APIRouter()


@router.get("/")
def list_schedules() -> dict:
    """TODO(Story2)。"""
    return {"todo": "implement Story2 - 见 doc/04 调度节"}
