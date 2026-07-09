"""goals 表 Repository（纯 CRUD）。"""

from sqlalchemy import select

from app.models.goal import Goal
from app.repositories.base import BaseRepository


class GoalRepository(BaseRepository[Goal]):
    __model__ = Goal

    def get_by_name(self, name: str) -> Goal | None:
        return self.db.scalar(select(Goal).where(Goal.name == name))

    def count(self) -> int:
        return self.db.query(Goal).count()
