"""任务接口。详见《服务API文档 v2.0》任务节。

POST /tasks/{id}/confirm-complete   Story4A 智能体任务验收通过 -> 标记完成 + 即时级联
POST /tasks/{id}/post-confirm        Story4B 后置确认（可全取消）
DELETE /tasks/{id}                   Story9 物理删除
PATCH /tasks/{id}/status             Story9 状态变更（暂停/恢复/回退，经状态机校验）
"""

from fastapi import APIRouter

router = APIRouter()


@router.get("/")
def list_tasks() -> dict:
    """TODO(Story4A/4B/9)。"""
    return {"todo": "implement - 见 doc/04 任务节"}
