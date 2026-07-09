"""workspaces 表 Repository（纯 CRUD）。"""

from sqlalchemy import select

from app.models.workspace import Workspace
from app.repositories.base import BaseRepository


class WorkspaceRepository(BaseRepository[Workspace]):
    __model__ = Workspace

    def get_by_theme(self, theme_id: str) -> Workspace | None:
        """与专题 1:1，按 theme_id 唯一查询。"""
        return self.db.scalar(select(Workspace).where(Workspace.theme_id == theme_id))

    def count_by_status(self, status: str) -> int:
        return self.db.query(Workspace).filter(Workspace.status == status).count()
