"""themes 表 Repository（纯 CRUD）。"""

from sqlalchemy import select

from app.models.theme import Theme
from app.repositories.base import BaseRepository


class ThemeRepository(BaseRepository[Theme]):
    __model__ = Theme

    def list_by_goal(self, goal_id: str) -> list[Theme]:
        return list(self.db.scalars(select(Theme).where(Theme.goal_id == goal_id)))

    def count(self) -> int:
        return self.db.query(Theme).count()
