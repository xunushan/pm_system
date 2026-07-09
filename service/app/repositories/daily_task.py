"""daily_tasks 表 Repository（纯 CRUD + 按 daily_id/task_id 查询）。"""

from sqlalchemy import select

from app.models.daily_task import DailyTask
from app.repositories.base import BaseRepository


class DailyTaskRepository(BaseRepository[DailyTask]):
    __model__ = DailyTask

    def list_by_daily(self, daily_id: str) -> list[DailyTask]:
        """按 daily_id 查询当日所有勾选任务。"""
        return list(self.db.scalars(select(DailyTask).where(DailyTask.daily_id == daily_id)))
