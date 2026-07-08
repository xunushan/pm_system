"""H5 看板编辑接口（Story9，入口 C）。详见《服务API文档 v2.0》看板节 + 《系统架构文档》四。

H5 页面调本组接口：字段编辑 / 增删任务（物理删除）/ 阶段排序 / 状态变更
（暂停填 reason / 恢复 / 回退填 reason）。DB 为唯一真相源，无反向同步。
"""

from fastapi import APIRouter

router = APIRouter()


@router.get("/")
def list_board() -> dict:
    """TODO(Story9)。"""
    return {"todo": "implement Story9 - 见 doc/04 看板节"}
