"""status_change_log 表 Repository（纯 CRUD + 按实体/类型查询）。"""

from sqlalchemy import select

from app.models.status_change_log import StatusChangeLog
from app.repositories.base import BaseRepository


class StatusChangeLogRepository(BaseRepository[StatusChangeLog]):
    __model__ = StatusChangeLog

    def list_by_entity(self, entity_type: str, entity_id: str) -> list[StatusChangeLog]:
        """按实体查变更历史（审计回溯）。"""
        return list(
            self.db.scalars(
                select(StatusChangeLog)
                .where(
                    StatusChangeLog.entity_type == entity_type,
                    StatusChangeLog.entity_id == entity_id,
                )
                .order_by(StatusChangeLog.changed_at)
            )
        )
