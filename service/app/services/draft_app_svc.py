"""DraftAppSvc：草稿 CRUD 业务（含乐观锁）。

drafts 纯存储（不进 H5/多维表格），用于确认前数据传递。
事务由本类管理：写 DB -> commit。无 IO/HTTP（事务内禁止）。
乐观锁：version 不匹配 -> 409（ConflictError, code 1003）；过期 -> 1007。
"""

import json
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestError, ConflictError, DraftExpiredError, NotFoundError
from app.models.draft import Draft
from app.repositories.draft import DraftRepository
from app.schemas.draft import (
    DraftCreateData,
    DraftGetData,
    DraftUpdateData,
)

_DRAFT_STATUSES = {"pending", "confirmed", "expired", "discarded"}
_DRAFT_STORY_TYPES = {"plan", "schedule", "daily", "weekly", "edit", "config"}


class DraftAppSvc:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = DraftRepository(db)

    def create(
        self,
        *,
        user_id: str,
        story_type: str,
        content: dict,
        expires_at: datetime | None = None,
    ) -> DraftCreateData:
        """创建草稿。content 存为 JSON 字符串。"""
        if story_type not in _DRAFT_STORY_TYPES:
            raise BadRequestError(f"非法 story_type: {story_type}")
        # DB CHECK 约束也会兜底，此处先校验给出清晰错误
        if not isinstance(content, dict):
            raise BadRequestError("content 必须是 JSON 对象")

        draft = Draft(
            id=_uuid(),
            user_id=user_id,
            story_type=story_type,
            content=json.dumps(content, ensure_ascii=False),
            status="pending",
            version=1,
            expires_at=expires_at,
        )
        self.repo.create(draft)
        self.db.commit()
        return DraftCreateData(
            draft_id=draft.id,
            status=draft.status,
            created_at=_ensure(draft.created_at),
            expires_at=draft.expires_at,
        )

    def get(self, draft_id: str) -> DraftGetData:
        draft = self._require(draft_id)
        return self._to_get_data(draft)

    def update(self, *, draft_id: str, content: dict, version: int) -> DraftUpdateData:
        """更新草稿内容（乐观锁）。version 不匹配 -> 409(code 1003)。"""
        draft = self._require(draft_id)
        self._ensure_not_expired(draft)
        if not isinstance(content, dict):
            raise BadRequestError("content 必须是 JSON 对象")

        # 原子乐观锁更新：WHERE id=? AND version=? -> SET content, version+1
        updated = self.repo.update_content_atomic(
            draft_id, json.dumps(content, ensure_ascii=False), version
        )
        if updated is None:
            # 已确认存在 -> None 说明 version 不匹配（并发覆盖）-> 409
            raise ConflictError("草稿 version 不匹配（乐观锁冲突）")
        self.db.commit()
        # drafts 无 updated_at 列（doc/02 2.9），用 created_at 标记时间。
        return DraftUpdateData(
            draft_id=updated.id,
            version=updated.version,
            updated_at=_ensure(updated.created_at),
        )

    def delete(self, draft_id: str) -> None:
        draft = self._require(draft_id)
        self.repo.delete(draft.id)
        self.db.commit()

    # ---- 内部 ----
    def _require(self, draft_id: str) -> Draft:
        draft = self.repo.get(draft_id)
        if draft is None:
            raise NotFoundError(f"草稿不存在: {draft_id}")
        return draft

    @staticmethod
    def _ensure_not_expired(draft: Draft) -> None:
        if draft.status == "expired":
            raise DraftExpiredError()
        if draft.expires_at is not None and datetime.utcnow() > draft.expires_at:
            raise DraftExpiredError()

    @staticmethod
    def _to_get_data(draft: Draft) -> DraftGetData:
        try:
            content = json.loads(draft.content)
        except (json.JSONDecodeError, TypeError):
            content = {}
        return DraftGetData(
            draft_id=draft.id,
            user_id=draft.user_id,
            story_type=draft.story_type,
            entity_id=draft.entity_id,
            content=content,
            status=draft.status,
            version=draft.version,
            created_at=_ensure(draft.created_at),
            expires_at=draft.expires_at,
        )


def _uuid() -> str:
    from uuid import uuid4

    return str(uuid4())


def _ensure(value: datetime | None) -> datetime:
    """server_default 列在 flush 后应已就绪；缺失则回退当前时间。"""
    return value if value is not None else datetime.utcnow()
