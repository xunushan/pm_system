"""weekly_records 表 Repository（纯 CRUD + 按周查询）。"""

from sqlalchemy import select

from app.models.weekly_record import WeeklyRecord
from app.repositories.base import BaseRepository


class WeeklyRecordRepository(BaseRepository[WeeklyRecord]):
    __model__ = WeeklyRecord

    def get_by_week(self, week: str) -> WeeklyRecord | None:
        """按 ISO 周唯一查询（一周一条）。"""
        return self.db.scalar(select(WeeklyRecord).where(WeeklyRecord.week == week))
