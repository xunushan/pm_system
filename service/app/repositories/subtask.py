"""subtasks 表 Repository（纯 CRUD + 按 task_id/type 查询）。"""

from sqlalchemy import select

from app.models.subtask import Subtask
from app.repositories.base import BaseRepository


class SubtaskRepository(BaseRepository[Subtask]):
    __model__ = Subtask

    def list_by_task(self, task_id: str) -> list[Subtask]:
        """按 task_id 查询该任务的所有子任务（按 sort_order）。"""
        return list(
            self.db.scalars(
                select(Subtask).where(Subtask.task_id == task_id).order_by(Subtask.sort_order)
            )
        )

    def next_sort_order(self, task_id: str) -> int:
        """返回该 task 下下一个可用 sort_order（已有最大值 +1，从 1 起）。"""
        existing = self.list_by_task(task_id)
        if not existing:
            return 1
        return max(s.sort_order for s in existing) + 1
