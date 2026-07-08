"""项目空间接口（Story2/8）。详见《服务API文档 v2.0》项目空间节。

managed=1 系统托管（激活初始化 mkdir+git init+骨架含规范文件）；
managed=0 关联已有路径（跳过初始化，不创建任何文件）。激活后不能改 managed。
"""

from fastapi import APIRouter

router = APIRouter()


@router.get("/")
def list_workspaces() -> dict:
    """TODO(Story2)。"""
    return {"todo": "implement Story2 - 见 doc/04 项目空间节"}
