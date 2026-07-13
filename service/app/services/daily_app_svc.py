"""DailyAppSvc：当日计划推送（Story3 核心服务）。

两个方法：
  - get_plans_pool：只读预查询（已激活阶段+排除已暂停），供 pm-daily LLM 决策。
  - confirm：事务5步 INSERT daily_records/daily_tasks/subtasks + 事务后异步 opencode。

铁律（CLAUDE.md §3）：
  - Service 不调 LLM（§3#1）：pool 只查、confirm 只落库+异步触发。
  - executor 推断是 Skill 职责：pool 返回 theme_type 供 pm-daily LLM 推断。
  - 事务内禁 IO/HTTP（§3#3）：opencode dispatch 事务后异步。
  - 飞书 3 秒超时（§3#4）：confirm 仅 DB 写后立即返回，opencode 异步。
  - 无 drafts（§3#6）：确认前数据在卡片，确认时直接写库。

theme_type -> executor 映射（doc/05 §5.4，确定性规则，非 LLM 推断）：
  learning/research/source -> human
  dev/survey -> agent
  Service 用此映射确定 pre_subtask 锚点 task 和 agent serve 触发，不写 tasks.executor。
"""

import logging
from datetime import date, timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clients.feishu import (
    FeishuClient,
    build_daily_plan_card,
    build_daily_summary_card,
    build_done_card,
)
from app.clients.fileio import write_daily_md
from app.clients.opencode import OpenCodeClient
from app.core.card_registry import set_card_context
from app.core.exceptions import BadRequestError, ConflictError, NotFoundError
from app.core.times import now_utc_naive
from app.db.session import SessionLocal
from app.models.daily_record import DailyRecord
from app.models.daily_task import DailyTask
from app.models.phase import Phase
from app.models.subtask import Subtask
from app.models.task import Task
from app.models.theme import Theme
from app.models.workspace import Workspace
from app.repositories.daily_record import DailyRecordRepository
from app.repositories.daily_task import DailyTaskRepository
from app.repositories.phase import PhaseRepository
from app.repositories.subtask import SubtaskRepository
from app.repositories.task import TaskRepository
from app.repositories.theme import ThemeRepository
from app.schemas.daily import (
    ActivePhaseInfo,
    DailyConfirmData,
    DailyPoolData,
    DailySummaryConfirmData,
    DailySummaryData,
    DailySummaryPhaseHealth,
    DailySummaryTaskItem,
    PendingTaskInfo,
    PreSubtaskInput,
    YesterdayCompletedTask,
)
from app.services.stats_app_svc import StatsAppSvc

logger = logging.getLogger(__name__)

# 全局进行中阶段上限（doc/03 8.9）
MAX_ACTIVE_PHASES = 3

# theme_type -> executor 映射（doc/05 §5.4，确定性规则）
_HUMAN_TYPES = frozenset({"learning", "research", "source"})
_AGENT_TYPES = frozenset({"dev", "survey"})


def _iso_week(d: date) -> str:
    """ISO 周字符串，如 "2026-W27"。"""
    iso = d.isocalendar()
    return f"{iso[0]}-W{iso[1]}"


class DailyAppSvc:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.daily_repo = DailyRecordRepository(db)
        self.daily_task_repo = DailyTaskRepository(db)
        self.subtask_repo = SubtaskRepository(db)
        self.phase_repo = PhaseRepository(db)
        self.task_repo = TaskRepository(db)
        self.theme_repo = ThemeRepository(db)
        self.opencode = OpenCodeClient()

    # ---- GET /daily/summary/generate (Story5) ----

    def generate_summary(self, user_id: str, date_: date | None = None) -> DailySummaryData:
        """日终总结统计预查询（只读，纯 Service 代码）。

        统计查询复用 StatsAppSvc.get_daily_stats。文案/建议由 pm-summary LLM 生成，
        S5 不碰 LLM（铁律 §3#1）。不级联（级联已即时，铁律 §3 异议级联在 PATCH）。
        """
        stats = StatsAppSvc(self.db).get_daily_stats(user_id, date_)
        return DailySummaryData(
            date=stats.date,
            daily_id=stats.daily_id,
            is_confirmed=stats.is_confirmed,
            completed_tasks=[
                DailySummaryTaskItem(task_id=t.task_id, name=t.name, theme_name=t.theme_name)
                for t in stats.completed_tasks
            ],
            incomplete_tasks=[
                DailySummaryTaskItem(task_id=t.task_id, name=t.name, theme_name=t.theme_name)
                for t in stats.incomplete_tasks
            ],
            phase_health=[
                DailySummaryPhaseHealth(
                    phase_id=p.phase_id,
                    name=p.name,
                    completed=p.completed,
                    total=p.total,
                    rate=p.rate,
                    status=p.status,
                )
                for p in stats.phase_health
            ],
            active_phase_count=stats.active_phase_count,
            global_active_limit=stats.global_active_limit,
        )

    # ---- POST /daily/summary/confirm (Story5) ----

    def confirm_summary(self, daily_id: str) -> DailySummaryConfirmData:
        """确认日终总结。不级联（级联已即时），仅写快照 + 标记 is_confirmed。

        事务（doc/04 §3.5）：
          1. UPDATE daily_records SET is_confirmed=1, confirmed_at=now
          2. COMMIT（<200ms）

        事务后异步（路由层 BackgroundTasks 调 write_daily_md_async）：
          3. 写 daily.md 快照（纯文件 IO）
        """
        daily = self.daily_repo.get(daily_id)
        if daily is None:
            raise NotFoundError(f"每日计划记录不存在: {daily_id}")
        if daily.is_confirmed:
            # 幂等：已确认的重复点击（飞书回调重试/用户重复点击）直接返回成功，
            # 不抛 ConflictError，保证 webhook 能同步返回终态卡刷新（铁律 §11）。
            return DailySummaryConfirmData(daily_id=daily_id, confirmed=True, daily_md_path=None)

        daily.is_confirmed = True
        daily.confirmed_at = now_utc_naive()
        self.db.commit()

        # 事务后异步写 daily.md（路由层调 write_daily_md_async）
        return DailySummaryConfirmData(daily_id=daily_id, confirmed=True, daily_md_path=None)

    @staticmethod
    def write_daily_md_async(daily_id: str) -> str | None:
        """事务后异步写 daily.md 快照（独立 session，BackgroundTasks 调用）。

        从 daily_id 反查统计数据 -> 写入 vault/daily/{date}.md。

        user_id 硬编码为 "system"：当前系统单用户，daily_records 无 user_id 列，
        多用户场景需扩展 daily_records 增加 user_id 后从此传入。
        """
        db = SessionLocal()
        try:
            daily = db.get(DailyRecord, daily_id)
            if daily is None:
                return None
            stats = StatsAppSvc(db).get_daily_stats("system", daily.date)
            summary_data = {
                "completed_tasks": [
                    {"name": t.name, "theme_name": t.theme_name} for t in stats.completed_tasks
                ],
                "incomplete_tasks": [
                    {"name": t.name, "theme_name": t.theme_name} for t in stats.incomplete_tasks
                ],
                "phase_health": [
                    {
                        "name": p.name,
                        "completed": p.completed,
                        "total": p.total,
                        "rate": p.rate,
                        "status": p.status,
                    }
                    for p in stats.phase_health
                ],
                "summary": daily.summary,
            }
            return write_daily_md("system", daily.date, summary_data)
        except Exception:
            logger.exception("write_daily_md_async 失败: %s", daily_id)
            return None
        finally:
            db.close()

    # ---- GET /daily/plans/pool ----

    def get_plans_pool(self, user_id: str, date_: date | None = None) -> DailyPoolData:
        """今日任务池预查询（只读）。

        过滤已激活阶段（activated_at 有值）+ 排除已暂停（status != '已暂停'）。
        返回结构化数据供 pm-daily LLM 决策候选任务 + 推断 executor。
        """
        today = date_ if date_ is not None else now_utc_naive().date()
        yesterday = today - timedelta(days=1)

        yesterday_completed = self._query_yesterday_completed(yesterday)
        yesterday_unconfirmed = self._check_yesterday_unconfirmed(yesterday)
        active_phases = self._query_active_phases()
        pending_tasks = self._query_pending_tasks(active_phases)
        global_active_count = self.phase_repo.count_by_status("进行中")

        return DailyPoolData(
            date=today,
            yesterday_completed=yesterday_completed,
            yesterday_unconfirmed=yesterday_unconfirmed,
            active_phases=active_phases,
            pending_tasks=pending_tasks,
            global_active_count=global_active_count,
            global_active_limit=MAX_ACTIVE_PHASES,
        )

    def _query_yesterday_completed(self, yesterday: date) -> list[YesterdayCompletedTask]:
        """昨日 daily_tasks 中已完成的任务。"""
        y_record = self.daily_repo.get_by_date(yesterday)
        if y_record is None:
            return []
        rows = self.db.execute(
            select(Task.id, Task.name, Phase.name)
            .join(DailyTask, DailyTask.task_id == Task.id)
            .join(Phase, Task.phase_id == Phase.id)
            .where(DailyTask.daily_id == y_record.id, Task.status == "已完成")
        ).all()
        return [YesterdayCompletedTask(task_id=r[0], name=r[1], phase_name=r[2]) for r in rows]

    def _check_yesterday_unconfirmed(self, yesterday: date) -> bool:
        """昨日 daily_record 存在且 is_confirmed=false。"""
        y_record = self.daily_repo.get_by_date(yesterday)
        return y_record is not None and not y_record.is_confirmed

    def _query_active_phases(self) -> list[ActivePhaseInfo]:
        """已激活（activated_at 有值）且非已暂停的阶段。"""
        rows = self.db.execute(
            select(Phase, Theme)
            .join(Theme, Phase.theme_id == Theme.id)
            .where(Phase.activated_at.is_not(None), Phase.status != "已暂停")
        ).all()

        result: list[ActivePhaseInfo] = []
        for phase, theme in rows:
            tasks = self.task_repo.list_by_phase(phase.id)
            total = len(tasks)
            completed = sum(1 for t in tasks if t.status == "已完成")
            remaining = sum(1 for t in tasks if t.status == "待执行")
            result.append(
                ActivePhaseInfo(
                    phase_id=phase.id,
                    name=phase.name,
                    theme_name=theme.name,
                    theme_type=theme.type,
                    deadline=phase.deadline,
                    progress=f"{completed}/{total}",
                    remaining_tasks=remaining,
                )
            )
        return result

    def _query_pending_tasks(self, active_phases: list[ActivePhaseInfo]) -> list[PendingTaskInfo]:
        """活跃阶段下的待执行任务。"""
        if not active_phases:
            return []
        phase_ids = [p.phase_id for p in active_phases]
        rows = self.db.execute(
            select(Task, Phase, Theme)
            .join(Phase, Task.phase_id == Phase.id)
            .join(Theme, Phase.theme_id == Theme.id)
            .where(Task.phase_id.in_(phase_ids), Task.status == "待执行")
            .order_by(Task.sort_order)
        ).all()
        return [
            PendingTaskInfo(
                task_id=task.id,
                name=task.name,
                phase_id=phase.id,
                phase_name=phase.name,
                phase_deadline=phase.deadline,
                theme_type=theme.type,
            )
            for task, phase, theme in rows
        ]

    # ---- POST /daily/confirm ----

    def confirm(
        self,
        user_id: str,
        date_: date,
        task_ids: list[str],
        pre_subtasks: list[PreSubtaskInput],
        push_source: str = "manual",
    ) -> DailyConfirmData:
        """确认今日计划：事务 INSERT 3 表 + 事务后异步触发 opencode。

        事务5步（doc/04 §3.4）：
          1. 校验 task_ids 属于已激活未暂停阶段 + 当日未确认过
          2. INSERT daily_records（is_confirmed=false，S5 日终确认时才置 true）
          3. INSERT daily_tasks（UNIQUE 冲突 -> 409）
          4. INSERT subtasks（勾选的前置，type=前置，status=待执行）
          5. COMMIT（<200ms）

        事务后异步（路由层 BackgroundTasks 调 trigger_async，独立 session）：
          - dispatch_pre_subtasks（opencode 桩）
          - 若有 agent-type 任务 -> start_agent_serve（opencode 桩）
        """
        # ---- 1. 校验 ----
        tasks = self._validate_task_ids(task_ids)
        self._check_duplicate_confirm(date_)

        anchor_task_id = self._find_anchor_task(tasks)
        has_agent_task = any(self._task_theme_type(t) in _AGENT_TYPES for t in tasks)

        # ---- 2-4. 事务内：INSERT 3 表 ----
        daily = DailyRecord(
            id=str(uuid4()),
            date=date_,
            week=_iso_week(date_),
            push_source=push_source,
        )
        self.daily_repo.create(daily)

        for task_id in task_ids:
            dt = DailyTask(id=str(uuid4()), daily_id=daily.id, task_id=task_id)
            self.daily_task_repo.create(dt)

        pre_subtask_count = 0
        if pre_subtasks and anchor_task_id:
            sort_base = self.subtask_repo.next_sort_order(anchor_task_id)
            for idx, ps in enumerate(pre_subtasks):
                sub = Subtask(
                    id=str(uuid4()),
                    task_id=anchor_task_id,
                    sort_order=sort_base + idx,
                    name=ps.name,
                    description=ps.description,
                    type="前置",
                    status="待执行",
                )
                self.subtask_repo.create(sub)
                pre_subtask_count += 1

        # ---- 5. COMMIT（<200ms，事务内无 IO/HTTP）----
        self.db.commit()

        return DailyConfirmData(
            daily_id=daily.id,
            date=date_,
            task_count=len(task_ids),
            pre_subtask_count=pre_subtask_count,
            async_triggered=pre_subtask_count > 0 or has_agent_task,
        )

    @staticmethod
    def trigger_async(daily_id: str) -> None:
        """事务后异步触发（独立 session，BackgroundTasks 调用）。

        S3 桩：调 OpenCodeClient 的 no-op 方法。S4A 换成真 HTTP dispatch。

        从 daily_id 反查：
          - pre_subtasks -> dispatch_pre_subtasks
          - agent-type tasks -> start_agent_serve
        """
        db = SessionLocal()
        try:
            # 查 daily_tasks -> tasks -> phases -> themes 判断 agent-type
            dt_rows = db.execute(
                select(DailyTask.task_id).where(DailyTask.daily_id == daily_id)
            ).all()
            task_ids = [r[0] for r in dt_rows]
            if not task_ids:
                return

            client = OpenCodeClient(db)

            # 前置子任务 -> dispatch
            pre_subs = (
                db.execute(
                    select(Subtask).where(Subtask.task_id.in_(task_ids), Subtask.type == "前置")
                )
                .scalars()
                .all()
            )
            if pre_subs:
                client.dispatch_pre_subtasks(
                    [{"id": s.id, "name": s.name, "task_id": s.task_id} for s in pre_subs]
                )

            # agent-type 任务 -> start_agent_serve（逐任务下发首任务）
            # select Task 以构造 task dict（含 task_id/name/phase_id），
            # 循环对每个 agent 任务 dispatch（start_agent_serve 内部 start_serve 幂等、
            # _ensure_session 按 workspace 复用，多任务同 workspace 安全）。
            agent_rows = db.execute(
                select(Workspace, Task)
                .join(Theme, Workspace.theme_id == Theme.id)
                .join(Phase, Phase.theme_id == Theme.id)
                .join(Task, Task.phase_id == Phase.id)
                .where(Task.id.in_(task_ids), Theme.type.in_(tuple(_AGENT_TYPES)))
            ).all()
            for ws, task in agent_rows:
                client.start_agent_serve(
                    ws.id,
                    {"task_id": task.id, "name": task.name, "phase_id": task.phase_id},
                )
        except Exception:
            logger.exception("daily trigger_async 失败: %s", daily_id)
        finally:
            db.close()

    # ---- 校验辅助 ----

    def _validate_task_ids(self, task_ids: list[str]) -> list[Task]:
        """校验 task_ids：存在 + 属于已激活未暂停阶段。返回 Task 列表。"""
        tasks: list[Task] = []
        for tid in task_ids:
            task = self.task_repo.get(tid)
            if task is None:
                raise NotFoundError(f"任务不存在: {tid}")
            phase = self.phase_repo.get(task.phase_id)
            if phase is None or phase.activated_at is None:
                raise BadRequestError(f"任务 {tid} 所属阶段未激活")
            if phase.status == "已暂停":
                raise BadRequestError(f"任务 {tid} 所属阶段已暂停")
            tasks.append(task)
        return tasks

    def _check_duplicate_confirm(self, date_: date) -> None:
        """当日已确认过 -> 409（doc/04 1003）。"""
        existing = self.daily_repo.get_by_date(date_)
        if existing is not None:
            raise ConflictError(f"日期 {date_} 已有每日计划记录")

    def _find_anchor_task(self, tasks: list[Task]) -> str | None:
        """找到第一个 human-type 任务作为 pre_subtask 锚点。

        用 theme_type 映射（learning/research/source -> human，doc/05 §5.4）。
        前置只对人执行任务（doc/01 关键决策）。
        """
        for task in tasks:
            if self._task_theme_type(task) in _HUMAN_TYPES:
                return task.id
        return None

    def _task_theme_type(self, task: Task) -> str:
        """查 task 所属 theme 的 type。"""
        phase = self.phase_repo.get(task.phase_id)
        if phase is None:
            return "learning"  # 防御性默认
        theme = self.theme_repo.get(phase.theme_id)
        return theme.type if theme is not None else "learning"

    # ---- 推卡入口（schema 2.0，doc/09 §S3）----

    def push_daily_plan_card(
        self,
        date_str: str,
        candidate_tasks: list[dict],
        prerequisites: list[dict],
        chat_id: str,
    ) -> str | None:
        """推今日计划卡片（schema 2.0，doc/09 §S3 状态1）。

        事务后异步 IO（铁律 §3#3）：调 build_daily_plan_card + FeishuClient.send_card。
        send_card 返回 message_id 后存 Redis 映射 card:<message_id> ->
        {type:"daily_plan"}，供 confirm_btn form_submit 回调反查（P2 路由缺口落地）。

        注意：daily_record 在确认时才建（confirm），推卡时尚无 daily_id。
        story3 确认按钮是 form_submit（name=confirm_btn），form_value checker
        业务解析归 PR-D。

        :return: 飞书 message_id（未配置飞书时返回 None）。
        """
        card = build_daily_plan_card(date_str, candidate_tasks, prerequisites)
        message_id = FeishuClient().send_card(chat_id, card)
        if message_id:
            # confirm_btn 是 form_submit（无 action_id/task_id），回调靠 message_id 反查。
            # 存 date + prerequisites 映射，供 webhook 从 form_value.pre_<id> 查前置名称
            # （form_value 只给 bool，名称从 context 查）。
            set_card_context(
                message_id,
                {
                    "type": "daily_plan",
                    "date": date_str,
                    "prerequisites": [
                        {"id": p["subtask_id"], "name": p["name"]} for p in prerequisites
                    ],
                },
            )
        return message_id

    # ---- 推卡入口 + update_card 刷新（schema 2.0，doc/09 §S5）----

    def push_daily_summary_card(
        self,
        daily_id: str,
        date_str: str,
        completed_tasks: list[dict],
        incomplete_tasks: list[dict],
        phase_health: list[dict],
        chat_id: str,
    ) -> str | None:
        """推日终总结卡片（schema 2.0，doc/09 §S5 状态1）。

        事务后异步 IO（铁律 §3#3）：调 build_daily_summary_card + FeishuClient.send_card。
        send_card 返回 message_id 后存 Redis 映射 ->
        {type:"daily_summary", daily_id}，供 confirm_btn form_submit 回调反查 daily_id
        （P2 路由缺口落地，doc/09 §S5 状态1->2）。

        :return: 飞书 message_id（未配置飞书时返回 None）。
        """
        card = build_daily_summary_card(
            daily_id, date_str, completed_tasks, incomplete_tasks, phase_health
        )
        message_id = FeishuClient().send_card(chat_id, card)
        if message_id:
            set_card_context(message_id, {"type": "daily_summary", "daily_id": daily_id})
        return message_id

    # ---- 终态卡片构建（纯函数 + _from_db 供 webhook 同步返回）----

    @staticmethod
    def build_daily_plan_done_card(date_str: str, task_lines: str, pre_lines: str | None) -> dict:
        """构建今日计划已确认终态卡片（纯函数，doc/09 §S3 状态2）。

        绿色标题 + "✅ 今日计划已确认" + 勾选任务 + 前置 + 异步执行提示。
        """
        elements: list[dict] = [
            {"tag": "markdown", "content": "✅ **今日计划已确认**\n\n**今日任务：**"},
            {"tag": "div", "text": {"tag": "lark_md", "content": task_lines}},
        ]
        if pre_lines:
            elements.append({"tag": "hr"})
            elements.append({"tag": "markdown", "content": "**今日前置：**"})
            elements.append({"tag": "div", "text": {"tag": "lark_md", "content": pre_lines}})
        elements.append({"tag": "hr"})
        elements.append({"tag": "markdown", "content": "前置与智能体任务已异步执行。"})
        return build_done_card(f"📋 今日计划已确认（{date_str}）", "green", elements)

    @staticmethod
    def build_daily_plan_done_card_from_db(db: Session, daily_id: str) -> dict | None:
        """查询 DB + 构建今日计划已确认终态卡片（供 webhook 同步调用）。

        daily 不存在时返回 None。
        """
        daily = db.get(DailyRecord, daily_id)
        if daily is None:
            return None
        date_str = daily.date.isoformat()

        # 查 daily_tasks -> task names + executor
        dt_rows = db.execute(
            select(Task, Theme)
            .join(DailyTask, DailyTask.task_id == Task.id)
            .join(Phase, Task.phase_id == Phase.id)
            .join(Theme, Phase.theme_id == Theme.id)
            .where(DailyTask.daily_id == daily_id)
        ).all()
        task_lines = (
            "\n".join(f"· {task.name} {_executor_tag_inline(task.executor)}" for task, _ in dt_rows)
            or "· （无）"
        )

        # 查前置 subtasks
        pre_rows = (
            db.execute(
                select(Subtask).where(
                    Subtask.task_id.in_([r[0].id for r in dt_rows]), Subtask.type == "前置"
                )
            )
            .scalars()
            .all()
        )
        pre_lines = "\n".join(f"· {s.name}" for s in pre_rows) if pre_rows else None

        return DailyAppSvc.build_daily_plan_done_card(date_str, task_lines, pre_lines)

    @staticmethod
    def build_summary_done_card(date_str: str, task_list: str, phase_lines: str) -> dict:
        """构建日终总结已确认终态卡片（纯函数，doc/09 §S5 状态2）。

        绿色标题 + "✅ 日终总结已确认" + 任务最终状态（✅/❌）+ 阶段进展。
        """
        elements = [
            {"tag": "markdown", "content": "✅ **日终总结已确认**\n\n**今日任务最终状态：**"},
            {"tag": "div", "text": {"tag": "lark_md", "content": task_list}},
            {"tag": "hr"},
            {
                "tag": "markdown",
                "content": (f"**阶段进展：**\n{phase_lines}\n\n daily.md 快照已写入。"),
            },
        ]
        return build_done_card(f"📊 日终总结已确认（{date_str}）", "green", elements)

    @staticmethod
    def build_summary_done_card_from_db(db: Session, daily_id: str) -> dict | None:
        """查询 DB + 构建日终总结已确认终态卡片（供 webhook 同步调用）。

        daily 不存在时返回 None。
        """
        daily = db.get(DailyRecord, daily_id)
        if daily is None:
            return None
        date_str = daily.date.isoformat()
        stats = StatsAppSvc(db).get_daily_stats("system", daily.date)

        # 任务最终状态（✅/❌）
        task_lines = []
        for t in stats.completed_tasks:
            task_lines.append(f"· {t.name} ✅ 已完成")
        for t in stats.incomplete_tasks:
            task_lines.append(f"· {t.name} ❌ 未完成")
        task_list = "\n".join(task_lines) or "· （无任务）"

        # 阶段进展
        if stats.phase_health:
            phase_lines = "\n".join(
                f"· {p.name}：{p.completed}/{p.total} {p.status}" for p in stats.phase_health
            )
        else:
            phase_lines = "· （无阶段数据）"

        return DailyAppSvc.build_summary_done_card(date_str, task_list, phase_lines)

    # ---- 事务后异步 update_card 刷新终态（doc/09 §通用规则）----

    @staticmethod
    def refresh_daily_plan_done_async(message_id: str, daily_id: str) -> None:
        """事务后异步刷新今日计划卡到终态（独立 session，BackgroundTasks 调用）。

        §S3 状态2 已确认：绿色，"✅ 今日计划已确认" + 勾选任务 + 前置 + 异步执行提示。
        铁律 §3#3/#4：HTTP 事务后异步，满足飞书 3 秒回调。
        保留给非回调场景（定时任务、事件触发）；webhook 回调走同步返回（方案 B）。
        """
        db = SessionLocal()
        try:
            card = DailyAppSvc.build_daily_plan_done_card_from_db(db, daily_id)
            if card is not None:
                FeishuClient().update_card(message_id, card)
        except Exception:
            logger.exception("refresh_daily_plan_done_async 失败: daily=%s", daily_id)
        finally:
            db.close()

    @staticmethod
    def refresh_summary_done_async(message_id: str, daily_id: str) -> None:
        """事务后异步刷新日终总结卡到终态（独立 session，BackgroundTasks 调用）。

        §S5 状态2 已确认：绿色，"✅ 日终总结已确认" + 任务最终状态（✅/❌）+ 阶段进展。
        铁律 §3#3/#4：HTTP 事务后异步，满足飞书 3 秒回调。
        保留给非回调场景（定时任务、事件触发）；webhook 回调走同步返回（方案 B）。
        """
        db = SessionLocal()
        try:
            card = DailyAppSvc.build_summary_done_card_from_db(db, daily_id)
            if card is not None:
                FeishuClient().update_card(message_id, card)
        except Exception:
            logger.exception("refresh_summary_done_async 失败: daily=%s", daily_id)
        finally:
            db.close()


def _executor_tag_inline(executor: str | None) -> str:
    """内联 executor 标签（用于 daily plan done card 展示）。"""
    if executor is None:
        return ""
    if executor.startswith("["):
        return executor
    return {"human": "[人]", "agent": "[智能体]"}.get(executor, f"[{executor}]")
