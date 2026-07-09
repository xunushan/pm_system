"""drafts 表 Repository（纯 CRUD + 乐观锁原子更新）。

drafts 纯存储，不进 H5/多维表格。version 乐观锁防并发覆盖。
事务由 AppSvc 管理；本类只做数据访问（add/flush/query，不 commit）。
"""

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.models.draft import Draft


class DraftRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, draft: Draft) -> Draft:
        self.db.add(draft)
        self.db.flush()
        return draft

    def get(self, draft_id: str) -> Draft | None:
        return self.db.get(Draft, draft_id)

    def update_content_atomic(
        self, draft_id: str, content: str, expected_version: int
    ) -> Draft | None:
        """原子乐观锁更新：WHERE id=? AND version=? -> SET content, version+1。

        返回更新后的 Draft；未命中（id 不存在或 version 不匹配）返回 None。
        命中与否由 AppSvc 结合 get() 区分 404 / 409。
        """
        stmt = (
            update(Draft)
            .where(Draft.id == draft_id, Draft.version == expected_version)
            .values(content=content, version=expected_version + 1)
        )
        result = self.db.execute(stmt)
        if result.rowcount == 0:
            return None
        self.db.flush()
        # expire 使后续 get() 从 DB 重读（拿到新 version）
        self.db.expire_all()
        return self.get(draft_id)

    def delete(self, draft_id: str) -> bool:
        """删除草稿（确认后调用）。返回是否命中。"""
        result = self.db.execute(delete(Draft).where(Draft.id == draft_id))
        return result.rowcount > 0

    def list_by_user(self, user_id: str) -> list[Draft]:
        return list(self.db.scalars(select(Draft).where(Draft.user_id == user_id)))
