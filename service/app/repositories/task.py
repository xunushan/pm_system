"""tasks 表 Repository（纯 CRUD）。"""

from sqlalchemy import select

from app.models.task import Task
from app.repositories.base import BaseRepository


class TaskRepository(BaseRepository[Task]):
    __model__ = Task

    def list_by_phase(self, phase_id: str) -> list[Task]:
        return list(
            self.db.scalars(select(Task).where(Task.phase_id == phase_id).order_by(Task.sort_order))
        )

    def count(self) -> int:
        return self.db.query(Task).count()
