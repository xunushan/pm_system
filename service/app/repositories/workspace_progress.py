"""workspace_progress 表 Repository（纯 CRUD）。"""

from datetime import date

from sqlalchemy import select

from app.models.workspace_progress import WorkspaceProgress
from app.repositories.base import BaseRepository


class WorkspaceProgressRepository(BaseRepository[WorkspaceProgress]):
    __model__ = WorkspaceProgress

    def list_by_workspace(
        self, workspace_id: str, date_: date | None = None
    ) -> list[WorkspaceProgress]:
        """按 workspace_id 查询产出记录（可选过滤日期）。"""
        stmt = select(WorkspaceProgress).where(WorkspaceProgress.workspace_id == workspace_id)
        if date_ is not None:
            stmt = stmt.where(WorkspaceProgress.date == date_)
        return list(self.db.scalars(stmt.order_by(WorkspaceProgress.created_at)))

    def list_by_task(self, task_id: str) -> list[WorkspaceProgress]:
        """按 task_id 查询产出记录。"""
        return list(
            self.db.scalars(
                select(WorkspaceProgress)
                .where(WorkspaceProgress.task_id == task_id)
                .order_by(WorkspaceProgress.created_at)
            )
        )
