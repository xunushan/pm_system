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

import logging
from datetime import date
from uuid import uuid4

from sqlalchemy.orm import Session

from app.clients.feishu import (
    FeishuClient,
    build_done_card,
    build_schedule_card_a,
    build_schedule_card_b,
)
from app.clients.workspace import is_path_valid
from app.core import audit, cascade, state_machine
from app.core.card_registry import set_card_context
from app.core.exceptions import (
    BadRequestError,
    ConflictError,
    NotFoundError,
    QuotaExceededError,
)
from app.core.times import now_utc_naive
from app.db.session import SessionLocal
from app.models.goal import Goal
from app.models.phase import Phase
from app.models.theme import Theme
from app.models.workspace import Workspace
from app.repositories.goal import GoalRepository
from app.repositories.phase import PhaseRepository
from app.repositories.theme import ThemeRepository
from app.repositories.workspace import WorkspaceRepository
from app.schemas.schedule import (
    ActivatedPhase,
    ScheduleActivateData,
    ScheduleConfirmData,
    ScheduleItem,
)

# 全局进行中阶段上限（doc/03 8.9）
MAX_ACTIVE_PHASES = 3

logger = logging.getLogger(__name__)


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
        managed=0 的 path 存在性校验（文件系统 stat=IO）前置到事务外（铁律 §3#3）。
        """
        # 0. managed=0 path 存在性校验（事务外，纯入参校验，不依赖 DB）
        for item in items:
            if not item.managed:
                if not item.path:
                    raise BadRequestError(f"专题 {item.theme_id} managed=0 时 path 必填")
                if not is_path_valid(item.path):
                    raise BadRequestError(f"path 不存在: {item.path}")

        # 1. 校验 goal 存在
        goal = self.goal_repo.get(goal_id)
        if goal is None:
            raise NotFoundError(f"目标不存在: {goal_id}")

        # 全局进行中 + 本次 <= 3（doc/04 2.3: 1004 并发超限）
        active_count = self.phase_repo.count_by_status("进行中")
        if active_count + len(items) > MAX_ACTIVE_PHASES:
            raise QuotaExceededError(
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

        # managed/path（path 存在性已在 confirm 开头事务外前置校验）
        workspace_id = str(uuid4())
        if item.managed:
            # managed=1：path 系统生成（规则：data/workspaces/{workspace_id}）
            path = f"data/workspaces/{workspace_id}"
            ws_status = "未初始化"
        else:
            # managed=0：path 已在事务外校验存在性，此处直接用
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

    # ---- Story8: 阶段衔接激活（doc/04 3.3 POST /schedules/activate）----

    def activate(
        self, phase_id: str, deadline: date, user_id: str = "supervisor"
    ) -> ScheduleActivateData:
        """阶段衔接激活（Story8）：激活指定 phase，复用 S2 激活核心。

        与 confirm 的区别：
          - activate 激活**指定 phase**（衔接下一阶段），
            confirm 激活**首个未开始 phase**（首次调度）
          - triggered_by='supervisor'（doc/04 line 310）
          - workspace 复用同专题已有 workspace（1:1）；无则建 managed=1

        事务内（doc/04 约 307-312）：
          1. 校验 phase 存在 + 状态未开始 + 全局进行中 < 3 + 同专题无进行中
          2. UPDATE phase + state_machine + audit(forward, supervisor)
          3. 即时级联（激活级联 phase->theme->goal）
          4. COMMIT
        事务后异步：managed=1 工作空间初始化（由路由层 BackgroundTasks 调度）。
        """
        phase = self.phase_repo.get(phase_id)
        if phase is None:
            raise NotFoundError(f"阶段不存在: {phase_id}")

        if phase.status != "未开始":
            raise ConflictError(f"阶段 {phase_id} 状态为 {phase.status}，仅未开始可激活")

        # 全局进行中 + 本次 <= 3（doc/03 8.9）
        active_count = self.phase_repo.count_by_status("进行中")
        if active_count + 1 > MAX_ACTIVE_PHASES:
            raise QuotaExceededError(
                f"进行中阶段 {active_count} + 本次 1 超上限 {MAX_ACTIVE_PHASES}"
            )

        # 同专题不能有进行中 phase（强约束，doc/03 8.9）
        theme_phases = self.phase_repo.list_by_theme(phase.theme_id)
        if any(p.status == "进行中" for p in theme_phases):
            raise ConflictError(f"专题 {phase.theme_id} 已有进行中阶段")

        theme = self.theme_repo.get(phase.theme_id)
        if theme is None:
            raise NotFoundError(f"专题不存在: {phase.theme_id}")

        # 事务内：UPDATE phase + 校验状态机 + 审计 + 级联
        old_status = phase.status
        state_machine.validate_transition("phase", old_status, "进行中", None)
        phase.status = "进行中"
        phase.activated_at = now_utc_naive().date()
        phase.status_changed_at = now_utc_naive()
        phase.deadline = deadline
        audit.log_status_change(
            self.db,
            entity_type="phase",
            entity_id=phase.id,
            from_status=old_status,
            to_status="进行中",
            change_type="forward",
            triggered_by="supervisor",
        )

        # workspace：复用同专题已有 workspace（1:1）；无则建 managed=1
        workspace = self.workspace_repo.get_by_theme(theme.id)
        if workspace is None:
            workspace_id = str(uuid4())
            workspace = Workspace(
                id=workspace_id,
                theme_id=theme.id,
                path=f"data/workspaces/{workspace_id}",
                managed=True,
                status="未初始化",
                type=theme.type,
            )
            self.workspace_repo.create(workspace)
        # 激活级联（phase->theme->goal 未开始->进行中，写 cascade 审计）
        cascade.cascade_status(self.db, "phase", phase.id)

        # COMMIT（<200ms，事务内无 IO/HTTP）
        self.db.commit()

        return ScheduleActivateData(
            phase_id=phase.id,
            name=phase.name,
            status=phase.status,
            deadline=phase.deadline,
            workspace_id=workspace.id,
            workspace_managed=workspace.managed,
            workspace_status=workspace.status,
        )

    # ---- 推卡入口（schema 2.0，doc/09 §S2）----

    def push_schedule_card(
        self,
        goal_name: str,
        themes: list[dict],
        chat_id: str,
        h5_url: str = "",
    ) -> str | None:
        """推调度激活卡片 A-选专题（schema 2.0，doc/09 §S2 状态1）。

        事务后异步 IO（铁律 §3#3）：调 build_schedule_card_a + FeishuClient.send_card。
        send_card 返回 message_id 后存 Redis 映射 card:<message_id> ->
        {type:"schedule_a", goal_id}，供 next_btn form_submit 回调反查 goal_id
        （P2 路由缺口落地，doc/09 §S2 状态1->2）。

        :param themes: 专题列表，每项含 theme_id/name/type；首项可含 goal_id
            （存映射用，builder 不渲染 goal_id）。
        :return: 飞书 message_id（未配置飞书时返回 None）。
        """
        card = build_schedule_card_a(goal_name, themes, h5_url)
        message_id = FeishuClient().send_card(chat_id, card)
        if message_id:
            # next_btn 是 form_submit（无 action_id/goal_id），回调靠 message_id 反查
            goal_id = themes[0].get("goal_id", "") if themes else ""
            set_card_context(message_id, {"type": "schedule_a", "goal_id": goal_id})
        return message_id

    # ---- 终态卡片构建（纯函数 + _from_db 供 webhook 同步返回）----

    @staticmethod
    def build_schedule_card_b_from_db(
        db: Session, theme_ids: list[str], goal_id: str
    ) -> dict | None:
        """查询 DB + 构建调度卡片 B（供 webhook 同步返回 + patch_to_card_b_async 共用）。

        查每个选中专题的第 1 个未开始阶段 -> build_schedule_card_b。
        无可激活阶段时返回 None。
        """
        goal = db.get(Goal, goal_id) if goal_id else None
        goal_name = goal.name if goal else ""
        phases: list[dict] = []
        for theme_id in theme_ids:
            theme = db.get(Theme, theme_id)
            if theme is None:
                continue
            theme_phases = PhaseRepository(db).list_by_theme(theme_id)
            locked = next((p for p in theme_phases if p.status == "未开始"), None)
            if locked is None:
                continue
            phases.append(
                {
                    "theme_id": theme_id,
                    "theme_name": theme.name,
                    "phase_name": locked.name,
                    "type": theme.type,
                }
            )
        if not phases:
            return None
        return build_schedule_card_b(goal_name, phases)

    @staticmethod
    def build_schedule_done_card(goal_name: str, phase_lines: list[str], h5_url: str) -> dict:
        """构建调度已确认终态卡片（纯函数，doc/09 §S2 状态3）。

        绿色标题 + "✅ 调度已确认" + 激活阶段列表 + 工作空间提示。
        :param phase_lines: 已格式化的阶段行列表（"· 主题/阶段 - deadline ..."）
        """
        elements: list[dict] = [
            {
                "tag": "markdown",
                "content": f"**目标：{goal_name}**\n\n✅ **调度已确认，已激活以下阶段：**",
            },
        ]
        for line in phase_lines:
            elements.append({"tag": "div", "text": {"tag": "lark_md", "content": line}})
        elements.append({"tag": "hr"})
        if h5_url:
            elements.append(
                {
                    "tag": "markdown",
                    "content": f"工作空间正在初始化。调整请[前往配置页]({h5_url})",
                }
            )
        else:
            elements.append({"tag": "markdown", "content": "工作空间正在初始化。调整请前往配置页"})
        return build_done_card("🎯 调度已确认", "green", elements)

    @staticmethod
    def build_schedule_done_card_from_db(
        db: Session, goal_id: str, activated_phases: list[dict], h5_url: str = ""
    ) -> dict:
        """查询 DB + 构建调度已确认终态卡片（供 webhook 同步调用）。

        :param activated_phases: [{"phase_id": "...", "name": "...", "deadline": "2026-07-15"}, ...]
        """
        goal = db.get(Goal, goal_id) if goal_id else None
        goal_name = goal.name if goal else ""

        phase_lines: list[str] = []
        for ap in activated_phases:
            phase = db.get(Phase, ap.get("phase_id", ""))
            theme_name = ""
            if phase:
                theme = db.get(Theme, phase.theme_id)
                theme_name = theme.name if theme else ""
            deadline_str = ap.get("deadline", "")
            label = f"{theme_name} / {ap.get('name', '')}" if theme_name else ap.get("name", "")
            phase_lines.append(f"· {label} - deadline {deadline_str}")

        return ScheduleAppSvc.build_schedule_done_card(goal_name, phase_lines, h5_url)

    @staticmethod
    def build_activate_done_card(phase_name: str, deadline_str: str) -> dict:
        """构建阶段已激活终态卡片（纯函数，doc/09 §S8 状态2）。

        绿色标题 + "✅ 下一阶段已激活" + deadline + 工作空间提示。
        """
        elements = [
            {
                "tag": "markdown",
                "content": (
                    f"✅ **下一阶段已激活：{phase_name}**\n\n"
                    f"· deadline：{deadline_str}\n"
                    "· 工作空间已就绪\n\n"
                    "阶段已进入进行中，即时级联已触发。"
                ),
            }
        ]
        return build_done_card("✅ 阶段已激活", "green", elements)

    @staticmethod
    def build_defer_done_card(phase_name: str) -> dict:
        """构建阶段已暂缓终态卡片（纯函数，doc/09 §S8 状态3）。

        橙色标题 + "⏳ 已记录暂缓" + 24h 后提醒 + H5 链接提示。
        """
        elements = [
            {
                "tag": "markdown",
                "content": (
                    f"**下一阶段：{phase_name}**\n\n"
                    "⏳ **已记录暂缓激活，24 小时后将再次提醒**\n\n"
                    "如需立即激活，前往 H5 页面手动操作。"
                ),
            }
        ]
        return build_done_card("⏳ 已记录暂缓", "orange", elements)

    @staticmethod
    def build_defer_done_card_from_db(db: Session, phase_id: str) -> dict:
        """查询 DB + 构建阶段已暂缓终态卡片（供 webhook 同步调用）。"""
        phase = db.get(Phase, phase_id)
        phase_name = phase.name if phase else phase_id
        return ScheduleAppSvc.build_defer_done_card(phase_name)

    @staticmethod
    def patch_to_card_b_async(message_id: str, theme_ids: list[str], goal_id: str) -> None:
        """事务后异步：patch 卡片 A -> B（doc/09 §S2 状态1->2）。

        查每个选中专题的第 1 个未开始阶段 -> build_schedule_card_b -> update_card。
        铁律 §3#3：HTTP（update_card）事务后异步，满足飞书 3 秒回调。
        独立 session（BackgroundTasks 调用）。

        保留给非回调场景（定时任务、事件触发）；webhook 回调走同步返回（方案 B）。

        :param theme_ids: 用户勾选的专题 ID 列表（从 form_value.theme_<id> 提取）。
        :param goal_id: 卡片关联的目标 ID（从 card_registry 反查，可能为空）。
        """
        db = SessionLocal()
        try:
            card = ScheduleAppSvc.build_schedule_card_b_from_db(db, theme_ids, goal_id)
            if card is None:
                logger.warning("patch_to_card_b_async: 无可激活阶段, themes=%s", theme_ids)
                return
            FeishuClient().update_card(message_id, card)
            # 更新 card_registry 类型 schedule_a -> schedule_b
            # 供 confirm_btn form_submit 回调区分（卡片 B 的确认调度 vs 其他 confirm_btn）
            set_card_context(message_id, {"type": "schedule_b", "goal_id": goal_id})
        except Exception:
            logger.exception("patch_to_card_b_async 失败: message_id=%s", message_id)
        finally:
            db.close()

    # ---- 事务后异步 update_card 刷新终态（doc/09 §通用规则）----

    @staticmethod
    def refresh_schedule_done_async(
        message_id: str, goal_id: str, activated_phases: list[dict], h5_url: str = ""
    ) -> None:
        """事务后异步刷新调度卡 B 到终态（独立 session，BackgroundTasks 调用）。

        §S2 状态3 已确认：绿色，"✅ 调度已确认" + 激活阶段 + deadline + 工作空间提示。
        铁律 §3#3/#4：HTTP 事务后异步，满足飞书 3 秒回调。
        保留给非回调场景（定时任务、事件触发）；webhook 回调走同步返回（方案 B）。

        :param activated_phases: [{"phase_id": "...", "name": "...", "deadline": "2026-07-15"}, ...]
        :param h5_url: H5 配置页链接（空则降级为纯文字提示，参考 build_schedule_card_a 模式）
        """
        db = SessionLocal()
        try:
            card = ScheduleAppSvc.build_schedule_done_card_from_db(
                db, goal_id, activated_phases, h5_url
            )
            FeishuClient().update_card(message_id, card)
        except Exception:
            logger.exception("refresh_schedule_done_async 失败: goal=%s", goal_id)
        finally:
            db.close()

    @staticmethod
    def refresh_activate_done_async(message_id: str, phase_name: str, deadline_str: str) -> None:
        """事务后异步刷新衔接卡到已激活态（BackgroundTasks 调用）。

        §S8 状态2 已激活：绿色，"✅ 下一阶段已激活" + deadline + 工作空间提示。
        铁律 §3#3/#4：HTTP 事务后异步，满足飞书 3 秒回调。
        保留给非回调场景（定时任务、事件触发）；webhook 回调走同步返回（方案 B）。
        """
        card = ScheduleAppSvc.build_activate_done_card(phase_name, deadline_str)
        try:
            FeishuClient().update_card(message_id, card)
        except Exception:
            logger.exception("refresh_activate_done_async 失败: phase=%s", phase_name)

    @staticmethod
    def refresh_defer_done_async(message_id: str, phase_id: str) -> None:
        """事务后异步刷新衔接卡到暂缓态（独立 session，BackgroundTasks 调用）。

        §S8 状态3 已暂缓：橙色，"⏳ 已记录暂缓" + 24h 后提醒 + H5 链接。
        铁律 §3#3/#4：HTTP 事务后异步，满足飞书 3 秒回调。
        保留给非回调场景（定时任务、事件触发）；webhook 回调走同步返回（方案 B）。
        """
        db = SessionLocal()
        try:
            card = ScheduleAppSvc.build_defer_done_card_from_db(db, phase_id)
            FeishuClient().update_card(message_id, card)
        except Exception:
            logger.exception("refresh_defer_done_async 失败: phase=%s", phase_id)
        finally:
            db.close()
