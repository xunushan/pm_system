"""草稿接口（Story1，规避飞书回调约 30KB 限制）。

详见《服务API文档 v2.0》3.1。纯存储，不同步展示；乐观锁 version。
  POST   /drafts         写入规划 JSON
  GET    /drafts/{id}     读
  PUT    /drafts/{id}     追加/改（version 校验）
  DELETE /drafts/{id}     删
"""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.common import ApiResponse
from app.schemas.draft import (
    DraftCreateData,
    DraftCreateRequest,
    DraftGetData,
    DraftUpdateData,
    DraftUpdateRequest,
)
from app.services.draft_app_svc import DraftAppSvc

router = APIRouter()

DBSession = Annotated[Session, Depends(get_db)]


@router.post("", response_model=ApiResponse[DraftCreateData], status_code=status.HTTP_201_CREATED)
def create_draft(payload: DraftCreateRequest, db: DBSession) -> ApiResponse[DraftCreateData]:
    data = DraftAppSvc(db).create(
        user_id=payload.user_id,
        story_type=payload.story_type,
        content=payload.content,
        expires_at=payload.expires_at,
    )
    return ApiResponse(data=data)


@router.get("/{draft_id}", response_model=ApiResponse[DraftGetData])
def get_draft(draft_id: str, db: DBSession) -> ApiResponse[DraftGetData]:
    data = DraftAppSvc(db).get(draft_id)
    return ApiResponse(data=data)


@router.put("/{draft_id}", response_model=ApiResponse[DraftUpdateData])
def update_draft(
    draft_id: str, payload: DraftUpdateRequest, db: DBSession
) -> ApiResponse[DraftUpdateData]:
    data = DraftAppSvc(db).update(
        draft_id=draft_id, content=payload.content, version=payload.version
    )
    return ApiResponse(data=data)


@router.delete("/{draft_id}", response_model=ApiResponse)
def delete_draft(draft_id: str, db: DBSession) -> ApiResponse:
    DraftAppSvc(db).delete(draft_id)
    return ApiResponse(message="草稿已删除")
