"""daily_records 表 Repository（纯 CRUD + 按日期查询）。"""

from datetime import date

from sqlalchemy import select

from app.models.daily_record import DailyRecord
from app.repositories.base import BaseRepository


class DailyRecordRepository(BaseRepository[DailyRecord]):
    __model__ = DailyRecord

    def get_by_date(self, date_: date) -> DailyRecord | None:
        """按日期唯一查询（一天一条）。"""
        return self.db.scalar(select(DailyRecord).where(DailyRecord.date == date_))
