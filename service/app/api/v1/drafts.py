"""草稿接口（Story1，规避飞书回调约 30KB 限制）。详见《服务API文档 v2.0》drafts 节。

纯存储，不同步展示；乐观锁 version，24h 过期。确认按钮只传 draft_id。
  POST   /drafts         写入规划 JSON
  GET    /drafts/{id}     读
  PUT    /drafts/{id}     追加/改（version 校验）
  DELETE /drafts/{id}     删
"""

from fastapi import APIRouter

router = APIRouter()


@router.get("/")
def list_drafts() -> dict:
    """TODO(Story1)。"""
    return {"todo": "implement Story1 - 见 doc/04 drafts 节"}
