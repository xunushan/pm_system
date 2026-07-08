"""周总结接口（Story6）。详见《服务API文档 v2.0》周总结节。"""

from fastapi import APIRouter

router = APIRouter()


@router.get("/")
def list_weekly() -> dict:
    """TODO(Story6)。"""
    return {"todo": "implement Story6 - 见 doc/04 周总结节"}
