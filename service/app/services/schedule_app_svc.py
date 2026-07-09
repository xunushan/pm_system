"""ScheduleAppSvc：调度激活（Story2 核心事务）。

doc/04 §3.3 事务 6 步：
  1. 校验全局进行中 + 本次 <= 3（已暂停不占名额）
  2. 阶段自动锁定（sort_order 最小的未开始 phase）+ phase_id 一致性校验
  3. 校验 deadline 必填 + managed/path（managed=0 校验 path 存在 1002）
  4. 事务内：UPDATE phases(进行中,activated_at,deadline) + 创建 workspace +
     state_machine.validate + audit(forward) + cascade(激活级联)
  5. COMMIT（<200ms）
  6. 事务后异步：managed=1 工作空间初始化（由路由层 BackgroundTasks 调 WorkspaceAppSvc.init）

铁律：事务内仅 DB 写 + 即时级联（纯 DB）；mkdir/git init 事务后异步（§3#3/#4）。
"""

from uuid import uuid4

from sqlalchemy.orm import Session

from app.clients.workspace import is_path_valid
from app.core import audit, cascade, state_machine
from app.core.exceptions import BadRequestError, ConflictError, NotFoundError
from app.core.times import now_utc_naive
from app.models.workspace import Workspace
from app.repositories.goal import GoalRepository
from app.repositories.phase import PhaseRepository
from app.repositories.theme import ThemeRepository
from app.repositories.workspace import WorkspaceRepository
from app.schemas.schedule import (
    ActivatedPhase,
    ScheduleConfirmData,
    ScheduleItem,
)

# 全局进行中阶段上限（doc/03 8.9）
MAX_ACTIVE_PHASES = 3


class ScheduleAppSvc:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.goal_repo = GoalRepository(db)
        self.theme_repo = ThemeRepository(db)
        self.phase_repo = PhaseRepository(db)
        self.workspace_repo = WorkspaceRepository(db)

    def confirm(self, user_id: str, goal_id: str, items: list[ScheduleItem]) -> ScheduleConfirmData:
        """确认调度：多选专题 -> 激活各自第1个未开始阶段 + 即时级联 + 审计。

        事务内完成所有 DB 写；工作空间初始化（managed=1）由路由层异步调度。
        """
        # 1. 校验 goal 存在
        goal = self.goal_repo.get(goal_id)
        if goal is None:
            raise NotFoundError(f"目标不存在: {goal_id}")

        # 全局进行中 + 本次 <= 3
        active_count = self.phase_repo.count_by_status("进行中")
        if active_count + len(items) > MAX_ACTIVE_PHASES:
            raise ConflictError(
                f"进行中阶段 {active_count} + 本次 {len(items)} 超上限 {MAX_ACTIVE_PHASES}"
            )

        # 2-3. 逐 item 校验 + 收集激活计划
        plans = [self._plan_item(item) for item in items]

        # 4. 事务内：更新 phase + 创建 workspace + 校验状态机 + 审计 + 级联
        activated: list[tuple] = []
        for plan in plans:
            phase = plan["phase"]
            old_status = phase.status
            state_machine.validate_transition("phase", old_status, "进行中", None)
            phase.status = "进行中"
            phase.activated_at = now_utc_naive().date()
            phase.status_changed_at = now_utc_naive()
            phase.deadline = plan["deadline"]
            audit.log_status_change(
                self.db,
                entity_type="phase",
                entity_id=phase.id,
                from_status=old_status,
                to_status="进行中",
                change_type="forward",
                triggered_by="user",
            )

            workspace = Workspace(
                id=plan["workspace_id"],
                theme_id=plan["theme"].id,
                path=plan["path"],
                managed=plan["managed"],
                status=plan["ws_status"],
                type=plan["theme"].type,
            )
            self.workspace_repo.create(workspace)

            # 激活级联（phase->theme->goal 未开始->进行中，写 cascade 审计）
            cascade.cascade_status(self.db, "phase", phase.id)
            activated.append((phase, workspace))

        # 5. COMMIT（<200ms，事务内无 IO/HTTP）
        self.db.commit()

        # 6. 响应（工作空间初始化异步，由路由层 BackgroundTasks 调度）
        return ScheduleConfirmData(
            activated_phases=[
                ActivatedPhase(
                    phase_id=phase.id,
                    name=phase.name,
                    deadline=phase.deadline,
                    workspace_id=ws.id,
                    workspace_managed=ws.managed,
                    workspace_status=ws.status,
                )
                for phase, ws in activated
            ],
            scheduled_start_date=goal.scheduled_start_date,
            bitable_synced=False,
        )

    def _plan_item(self, item: ScheduleItem) -> dict:
        """校验单个 item 并返回激活计划（不写 DB）。"""
        theme = self.theme_repo.get(item.theme_id)
        if theme is None:
            raise NotFoundError(f"专题不存在: {item.theme_id}")

        # 阶段强约束：同专题已有进行中 phase -> 拒绝（应走衔接 Story8）
        phases = self.phase_repo.list_by_theme(item.theme_id)
        if any(p.status == "进行中" for p in phases):
            raise ConflictError(f"专题 {item.theme_id} 已有进行中阶段，请先完成或走衔接")

        # 自动锁定 sort_order 最小的未开始 phase
        locked = next((p for p in phases if p.status == "未开始"), None)
        if locked is None:
            raise ConflictError(f"专题 {item.theme_id} 无未开始阶段可激活")
        if item.phase_id is not None and item.phase_id != locked.id:
            raise BadRequestError(f"phase_id {item.phase_id} 与锁定的阶段 {locked.id} 不一致")

        # deadline 必填
        if item.deadline is None:
            raise BadRequestError(f"专题 {item.theme_id} 的 deadline 必填")

        # managed/path
        workspace_id = str(uuid4())
        if item.managed:
            # managed=1：path 系统生成（规则：data/workspaces/{workspace_id}）
            path = f"data/workspaces/{workspace_id}"
            ws_status = "未初始化"
        else:
            # managed=0：path 必填且校验存在性（不创建任何文件）
            if not item.path:
                raise BadRequestError(f"专题 {item.theme_id} managed=0 时 path 必填")
            if not is_path_valid(item.path):
                raise BadRequestError(f"path 不存在: {item.path}")
            path = item.path
            ws_status = "已就绪"

        return {
            "theme": theme,
            "phase": locked,
            "deadline": item.deadline,
            "managed": item.managed,
            "path": path,
            "workspace_id": workspace_id,
            "ws_status": ws_status,
        }
