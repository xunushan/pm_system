"""phases 表 Repository（纯 CRUD）。"""

from sqlalchemy import select

from app.models.phase import Phase
from app.repositories.base import BaseRepository


class PhaseRepository(BaseRepository[Phase]):
    __model__ = Phase

    def list_by_theme(self, theme_id: str) -> list[Phase]:
        return list(
            self.db.scalars(
                select(Phase).where(Phase.theme_id == theme_id).order_by(Phase.sort_order)
            )
        )

    def count(self) -> int:
        return self.db.query(Phase).count()
