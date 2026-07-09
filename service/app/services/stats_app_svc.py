"""StatsAppSvc：日终/周总结共用统计查询核心（Story5，doc/05 §8.1）。

纯查询，无 LLM，无副作用。pm-summary Skill 调用本服务获取统计数据，
文案与建议由 LLM 生成（Service 不调 LLM，铁律 §3#1）。
"""

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.times import now_utc_naive
from app.models.daily_task import DailyTask
from app.models.phase import Phase
from app.models.task import Task
from app.models.theme import Theme
from app.repositories.daily_record import DailyRecordRepository
from app.repositories.phase import PhaseRepository
from app.repositories.task import TaskRepository
from app.schemas.stats import DailyStatsData, PhaseHealthItem, TaskStatItem

# 全局进行中阶段上限（doc/03 8.9）
MAX_ACTIVE_PHASES = 3


class StatsAppSvc:
    """纯查询统计服务（日终/周总结共用）。"""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.daily_repo = DailyRecordRepository(db)
        self.phase_repo = PhaseRepository(db)
        self.task_repo = TaskRepository(db)

    def get_daily_stats(self, user_id: str, date_: date | None = None) -> DailyStatsData:
        """日终统计查询（只读，无 LLM，无副作用）。

        返回：date, daily_id, is_confirmed, completed_tasks, incomplete_tasks,
        phase_health, active_phase_count, global_active_limit。
        """
        today = date_ if date_ is not None else now_utc_naive().date()

        # 查当日 daily_record
        daily = self.daily_repo.get_by_date(today)
        daily_id = daily.id if daily else None
        is_confirmed = daily.is_confirmed if daily else False

        # 查当日 daily_tasks 关联的任务
        completed_tasks: list[TaskStatItem] = []
        incomplete_tasks: list[TaskStatItem] = []

        if daily is not None:
            rows = self.db.execute(
                select(Task, Theme.name)
                .join(DailyTask, DailyTask.task_id == Task.id)
                .join(Phase, Task.phase_id == Phase.id)
                .join(Theme, Phase.theme_id == Theme.id)
                .where(DailyTask.daily_id == daily.id)
                .order_by(Task.sort_order)
            ).all()
            for task, theme_name in rows:
                item = TaskStatItem(task_id=task.id, name=task.name, theme_name=theme_name)
                if task.status == "已完成":
                    completed_tasks.append(item)
                else:
                    incomplete_tasks.append(item)

        # 阶段健康度（已激活阶段）
        phase_health = self._query_phase_health()
        active_phase_count = self.phase_repo.count_by_status("进行中")

        return DailyStatsData(
            date=today,
            daily_id=daily_id,
            is_confirmed=is_confirmed,
            completed_tasks=completed_tasks,
            incomplete_tasks=incomplete_tasks,
            phase_health=phase_health,
            active_phase_count=active_phase_count,
            global_active_limit=MAX_ACTIVE_PHASES,
        )

    def _query_phase_health(self) -> list[PhaseHealthItem]:
        """已激活（activated_at 有值）且非已暂停的阶段的健康度。"""
        rows = self.db.execute(
            select(Phase, Theme.name)
            .join(Theme, Phase.theme_id == Theme.id)
            .where(Phase.activated_at.is_not(None), Phase.status != "已暂停")
        ).all()

        result: list[PhaseHealthItem] = []
        for phase, _theme_name in rows:
            tasks = self.task_repo.list_by_phase(phase.id)
            total = len(tasks)
            completed = sum(1 for t in tasks if t.status == "已完成")
            rate = completed / total if total > 0 else 0.0
            result.append(
                PhaseHealthItem(
                    phase_id=phase.id,
                    name=phase.name,
                    completed=completed,
                    total=total,
                    rate=round(rate, 2),
                    status=phase.status,
                )
            )
        return result
