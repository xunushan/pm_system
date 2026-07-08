"""规划接口（Story1）。详见《服务API文档 v2.0》规划节。

关键端点：
  POST /plans/draft          pm-plan 逐专题追加规划到 drafts
  PUT  /plans/draft/{id}      追加/修改草案内容（乐观锁 version）
  POST /plans/confirm        确认：用 draft_id 读 drafts -> 写正式表 -> 删 drafts
"""

from fastapi import APIRouter

router = APIRouter()


@router.get("/")
def list_plans() -> dict:
    """TODO(Story1)。"""
    return {"todo": "implement Story1 - 见 doc/04_服务API文档_v2.0.md 规划节"}
