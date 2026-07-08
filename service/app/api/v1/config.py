"""配置接口（Story7）。详见《服务API文档 v2.0》配置节。

子任务模板 CRUD（scope_type=theme/phase，阶段级优先于专题级，同名去重）。
走 H5 页面，不建 Skill。
"""

from fastapi import APIRouter

router = APIRouter()


@router.get("/")
def list_config() -> dict:
    """TODO(Story7)。"""
    return {"todo": "implement Story7 - 见 doc/04 配置节"}
