"""StatsAppSvc：日终/周总结共用统计查询核心（Story5/Story6，doc/05 §8.1）。

纯查询，无 LLM，无副作用。pm-summary Skill 调用本服务获取统计数据，
文案与建议由 LLM 生成（Service 不调 LLM，铁律 §3#1）。
"""

from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestError
from app.core.times import now_utc_naive
from app.models.daily_record import DailyRecord
from app.models.daily_task import DailyTask
from app.models.phase import Phase
from app.models.subtask import Subtask
from app.models.task import Task
from app.models.theme import Theme
from app.models.workspace_progress import WorkspaceProgress
from app.repositories.daily_record import DailyRecordRepository
from app.repositories.phase import PhaseRepository
from app.repositories.task import TaskRepository
from app.schemas.stats import DailyStatsData, PhaseHealthItem, TaskStatItem
from app.schemas.weekly import (
    AgentOutputStats,
    DailyStatsItem,
    DateRange,
    SubtaskStats,
    SubtaskStatsItem,
    SupervisorLinkingStatus,
    WeeklyCompletedTaskItem,
    WeeklyStatsData,
)

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

    # ---- 周统计（Story6）----

    def get_weekly_stats(self, user_id: str, week: str) -> WeeklyStatsData:
        """周统计查询（只读，无 LLM，无副作用）。

        聚合本周（ISO 周）的每日完成趋势、阶段健康度、智能体产出、子任务统计。
        supervisor_linking_status 由 Supervisor 衔接逻辑填充（Story8，查当前衔接下一阶段）。
        """
        start, end = self._parse_week(week)

        daily_stats = self._query_daily_stats_for_week(start, end)
        completed_tasks = self._query_completed_tasks_for_week(start, end)
        phase_health = self._query_phase_health()
        agent_output_stats = self._query_agent_output_stats(start, end)
        subtask_stats = self._query_subtask_stats(start, end)
        # Supervisor 衔接状态（Story8：查当前进行中/最近完成阶段的下一阶段）
        from app.supervisor.linking import get_linking_status

        next_phase_id, suggested_deadline = get_linking_status(self.db)
        supervisor_linking_status = SupervisorLinkingStatus(
            next_phase=next_phase_id, suggested_deadline=suggested_deadline
        )

        return WeeklyStatsData(
            week=week,
            date_range=DateRange(start=start, end=end),
            daily_stats=daily_stats,
            completed_tasks=completed_tasks,
            phase_health=phase_health,
            agent_output_stats=agent_output_stats,
            subtask_stats=subtask_stats,
            supervisor_linking_status=supervisor_linking_status,
        )

    @staticmethod
    def _parse_week(week: str) -> tuple[date, date]:
        """ISO 周字符串 -> (周一, 周日)。如 "2026-W27" -> (2026-06-29, 2026-07-05)。

        用 date.fromisocalendar（Python 3.9+），与 daily_records.week 的 _iso_week 互逆。
        """
        parts = week.split("-W")
        if len(parts) != 2:
            raise BadRequestError(f"非法 ISO 周格式: {week}（期望如 2026-W27）")
        try:
            year, w = int(parts[0]), int(parts[1])
            start = date.fromisocalendar(year, w, 1)  # 周一
            end = date.fromisocalendar(year, w, 7)  # 周日
        except (ValueError, IndexError) as exc:
            raise BadRequestError(f"非法 ISO 周格式: {week}") from exc
        return start, end

    def _query_daily_stats_for_week(self, start: date, end: date) -> list[DailyStatsItem]:
        """本周各天完成趋势（周一~周日逐天，无 daily_record 的天补 0）。"""
        records = list(
            self.db.scalars(select(DailyRecord).where(DailyRecord.date.between(start, end)))
        )
        record_by_date = {r.date: r for r in records}

        result: list[DailyStatsItem] = []
        cur = start
        while cur <= end:
            rec = record_by_date.get(cur)
            if rec is not None:
                rows = self.db.execute(
                    select(Task.status)
                    .join(DailyTask, DailyTask.task_id == Task.id)
                    .where(DailyTask.daily_id == rec.id)
                ).all()
                completed = sum(1 for (s,) in rows if s == "已完成")
                incomplete = sum(1 for (s,) in rows if s != "已完成")
                result.append(
                    DailyStatsItem(
                        date=cur,
                        is_confirmed=rec.is_confirmed,
                        completed_count=completed,
                        incomplete_count=incomplete,
                    )
                )
            else:
                result.append(
                    DailyStatsItem(
                        date=cur, is_confirmed=False, completed_count=0, incomplete_count=0
                    )
                )
            cur += timedelta(days=1)
        return result

    def _query_completed_tasks_for_week(
        self, start: date, end: date
    ) -> list[WeeklyCompletedTaskItem]:
        """本周已完成任务列表（按 tasks.completed_at 聚合到周，doc/09 §S6）。

        纯确定性查询（铁律 §3#1）：completed_at 落在 [start, end] 内的已完成任务，
        JOIN theme 取 theme_name，executor 取 tasks.executor（规划态可空）。
        供 push_weekly_summary_card_from_db 组装周总结卡「本周完成任务」+ pm-summary 参考。
        """
        start_dt = datetime.combine(start, datetime.min.time())
        end_dt = datetime.combine(end, datetime.max.time())
        rows = self.db.execute(
            select(Task, Theme.name)
            .join(Phase, Task.phase_id == Phase.id)
            .join(Theme, Phase.theme_id == Theme.id)
            .where(Task.status == "已完成", Task.completed_at.is_not(None))
            .where(Task.completed_at.between(start_dt, end_dt))
            .order_by(Task.completed_at)
        ).all()
        result: list[WeeklyCompletedTaskItem] = []
        for task, theme_name in rows:
            completed_at = task.completed_at
            date_str = completed_at.date().isoformat() if completed_at else ""
            result.append(
                WeeklyCompletedTaskItem(
                    date=date_str,
                    task_name=task.name,
                    executor=task.executor,
                    theme_name=theme_name,
                )
            )
        return result

    def _query_agent_output_stats(self, start: date, end: date) -> AgentOutputStats:
        """本周智能体产出统计（workspace_progress 按 file_type 聚合）。"""
        rows = list(
            self.db.scalars(
                select(WorkspaceProgress).where(WorkspaceProgress.date.between(start, end))
            )
        )
        by_type: dict[str, int] = {}
        for r in rows:
            by_type[r.file_type] = by_type.get(r.file_type, 0) + 1
        return AgentOutputStats(total_files=len(rows), by_type=by_type)

    def _query_subtask_stats(self, start: date, end: date) -> SubtaskStats:
        """本周子任务统计（前置/后置，按 created_at 在周内过滤）。"""
        start_dt = datetime.combine(start, datetime.min.time())
        end_dt = datetime.combine(end, datetime.max.time())
        subs = list(
            self.db.scalars(select(Subtask).where(Subtask.created_at.between(start_dt, end_dt)))
        )
        pre = [s for s in subs if s.type == "前置"]
        post = [s for s in subs if s.type == "后置"]
        return SubtaskStats(pre=self._subtask_item(pre), post=self._subtask_item(post))

    @staticmethod
    def _subtask_item(subs: list[Subtask]) -> SubtaskStatsItem:
        total = len(subs)
        completed = sum(1 for s in subs if s.status == "已完成")
        pending = sum(1 for s in subs if s.status == "待执行")
        return SubtaskStatsItem(total=total, completed=completed, pending=pending)
