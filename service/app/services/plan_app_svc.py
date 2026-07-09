"""PlanAppSvc：规划确认（drafts -> 正式表 -> 删 drafts）。

Story1 核心事务接口。确认按钮回调只传 draft_id（规避飞书 30KB 限制）。
一个事务内写入 goals+themes+phases+tasks（初始状态），删 drafts，返回 H5 链接。

规划态铁律（CLAUDE.md §3 / doc/02 2.14）：
  - tasks.executor = NULL（pm-daily 按专题 type 推断）
  - phases.deadline = NULL（激活时填，Story2）
  - goals/themes/phases 初始 '未开始'，tasks 初始 '待执行'
  - 无"变为已完成"流转 -> 无即时向上级联、不写 status_change_log
事务内禁止 IO/HTTP；H5 链接直接返回（无异步副作用）。
"""

import json
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.config import settings
from app.core.exceptions import BadRequestError, ConflictError, NotFoundError
from app.models.goal import Goal
from app.models.phase import Phase
from app.models.task import Task
from app.models.theme import Theme
from app.repositories.draft import DraftRepository
from app.repositories.goal import GoalRepository
from app.repositories.phase import PhaseRepository
from app.repositories.task import TaskRepository
from app.repositories.theme import ThemeRepository
from app.schemas.plan import PlanConfirmData, PlanContent


class PlanAppSvc:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.draft_repo = DraftRepository(db)
        self.goal_repo = GoalRepository(db)
        self.theme_repo = ThemeRepository(db)
        self.phase_repo = PhaseRepository(db)
        self.task_repo = TaskRepository(db)

    def confirm(self, draft_id: str) -> PlanConfirmData:
        """确认方案：读 draft -> 事务写 4 张正式表 -> 删 draft -> 返回 H5 链接。"""
        draft = self.draft_repo.get(draft_id)
        if draft is None:
            raise NotFoundError(f"草稿不存在: {draft_id}")
        if draft.status != "pending":
            raise ConflictError(f"草稿状态非 pending: {draft.status}")

        # 解析 draft.content 为 PlanContent
        try:
            content_raw = json.loads(draft.content)
        except (json.JSONDecodeError, TypeError) as e:
            raise BadRequestError(f"草稿 content 不是合法 JSON: {e}") from e
        if draft.story_type != "plan":
            raise BadRequestError(f"草稿 story_type 非 plan: {draft.story_type}")
        try:
            plan = PlanContent.model_validate(content_raw)
        except ValidationError as e:
            raise BadRequestError(f"规划内容结构不合法: {e}") from e

        # ---- 事务：写 DB -> commit（事务内无 IO/HTTP）----
        goal = self._create_goal(plan)
        themes_n = phases_n = tasks_n = 0
        for theme_item in plan.themes:
            theme = self._create_theme(theme_item, goal.id)
            themes_n += 1
            for phase_item in theme_item.phases:
                phase = self._create_phase(phase_item, theme.id)
                phases_n += 1
                for task_item in phase_item.tasks:
                    self._create_task(task_item, phase.id)
                    tasks_n += 1

        # 删 drafts（doc/04 3.2 事务步骤 6）
        draft_deleted = self.draft_repo.delete(draft_id)

        self.db.commit()

        return PlanConfirmData(
            goal_id=goal.id,
            goal_name=goal.name,
            themes_created=themes_n,
            phases_created=phases_n,
            tasks_created=tasks_n,
            draft_deleted=draft_deleted,
            h5_url=f"{settings.h5_base_url}/plan/{goal.id}",
        )

    # ---- 实体创建（初始状态，规划态）----
    def _create_goal(self, plan: PlanContent) -> Goal:
        goal = Goal(
            id=str(uuid4()),
            name=plan.goal.name,
            description=plan.goal.description,
            time_range_start=plan.goal.time_range_start,
            time_range_end=plan.goal.time_range_end,
            scheduled_start_date=plan.goal.scheduled_start_date,
            status="未开始",  # 规划态初始
        )
        self.goal_repo.create(goal)
        return goal

    def _create_theme(self, theme_item, goal_id: str) -> Theme:
        theme = Theme(
            id=str(uuid4()),
            goal_id=goal_id,
            name=theme_item.name,
            description=theme_item.description,
            type=theme_item.type,
            status="未开始",  # 规划态初始
        )
        self.theme_repo.create(theme)
        return theme

    def _create_phase(self, phase_item, theme_id: str) -> Phase:
        phase = Phase(
            id=str(uuid4()),
            theme_id=theme_id,
            sort_order=phase_item.sort_order,
            name=phase_item.name,
            description=phase_item.description,
            status="未开始",  # 规划态初始
            deadline=None,  # 规划态不填（激活时填，Story2）
        )
        self.phase_repo.create(phase)
        return phase

    def _create_task(self, task_item, phase_id: str) -> Task:
        task = Task(
            id=str(uuid4()),
            phase_id=phase_id,
            sort_order=task_item.sort_order,
            name=task_item.name,
            description=task_item.description,
            status="待执行",  # 规划态初始
            executor=None,  # 规划态不填（pm-daily 按专题 type 推断）
        )
        self.task_repo.create(task)
        return task
