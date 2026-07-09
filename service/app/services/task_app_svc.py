"""TaskAppSvc：任务完成与验收（Story4A + Story4B）。

Story4B 方法：
  - complete：标记任务完成 + 即时级联（完成和后置脱钩，不含后置）。
  - post_confirm：后置确认（INSERT 勾选的后置子任务，可全取消）+ 事务后异步执行。
  - create_subtask / get_subtask / patch_subtask：子任务 CRUD
    （供 pm-subtask Skill 与异步回调使用）。
  - trigger_post_async：事务后异步执行后置子任务。

Story4A 方法：
  - confirm_complete：4A 人工确认完成（3 次重试不通过，用户手动接管后调用）。即时级联，无后置。
  - output_confirm：验收通过智能体产出。即时级联。
  - output_reject：退回智能体产出，重试或通知。3 次不通过不改状态。
  - record_output：OpenCode 产出回调 -> 记录 workspace_progress + DEL 超时 + 发验收卡片。
  - handle_timeout：Redis 超时告警回调 -> 飞书通知。
  - trigger_reject_async：output_reject 事务后异步触发（dispatch/shutdown/通知）。

铁律（CLAUDE.md §3）：
  - Service 不调 LLM（§3#1）：complete/confirm 只标记完成+级联；
    验收卡片模板填充；后置内容由 pm-subtask Skill 生成。
  - 事务内禁 IO/HTTP（§3#3）：opencode dispatch/feishu/Redis 事务后异步。
  - 即时级联在事务内（§3#3）：cascade.cascade_status 在 commit 前。
  - 状态机（§3#7）：task forward 写 status_change_log。
  - 后置脱钩（§3#9）：complete 即时级联，后置可全取消。
  - 3次不通过不改状态（doc/01 4A要点）。
  - 智能体任务不生成前置/后置（doc/01 4A要点）。
"""

import logging
from datetime import datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clients.feishu import FeishuClient, build_daily_summary_card, build_verification_card
from app.clients.opencode import OpenCodeClient
from app.core import audit, cascade, state_machine
from app.core.exceptions import BadRequestError, ConflictError, NotFoundError
from app.core.task_timeout import del_task_timeout, set_task_timeout
from app.core.times import now_utc_naive
from app.db.session import SessionLocal
from app.models.subtask import Subtask
from app.models.task import Task
from app.models.workspace import Workspace
from app.models.workspace_progress import WorkspaceProgress
from app.repositories.agent_process import AgentProcessRepository
from app.repositories.subtask import SubtaskRepository
from app.repositories.task import TaskRepository
from app.repositories.workspace import WorkspaceRepository
from app.repositories.workspace_progress import WorkspaceProgressRepository
from app.schemas.subtask import SubtaskCreateRequest, SubtaskData, SubtaskPatchRequest
from app.schemas.task import (
    CascadeResult,
    ConfirmCompleteData,
    OutputConfirmData,
    OutputRejectData,
    PostConfirmData,
    PostSubtaskInput,
    RecordOutputData,
    RevertCascadeResult,
    TaskCompleteData,
    TaskDetailData,
    TaskPatchStatusData,
    TimeoutAlertData,
)
from app.supervisor.event_bus import emit

logger = logging.getLogger(__name__)

MAX_RETRY = 3

# 日终异议 revert 系统默认 reason（D18 裁决：不弹窗，系统自动填，满足 D6 reason 必填）
REVERT_REASON = "日终异议-标记未完成"


class TaskAppSvc:
    """任务完成与验收服务（Story4A + Story4B）。

    4A：confirm_complete / output_confirm / output_reject / record_output / handle_timeout。
    4B：complete / post_confirm / create_subtask / get_subtask / patch_subtask。
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self.task_repo = TaskRepository(db)
        self.subtask_repo = SubtaskRepository(db)
        self.workspace_repo = WorkspaceRepository(db)
        self.wp_repo = WorkspaceProgressRepository(db)
        self.agent_repo = AgentProcessRepository(db)
        self.opencode = OpenCodeClient(db)
        self.feishu = FeishuClient()

    # ---- GET /tasks/{taskId} ----

    def get_task(self, task_id: str) -> TaskDetailData:
        """获取任务详情（含 executor）。"""
        task = self.task_repo.get(task_id)
        if task is None:
            raise NotFoundError(f"任务不存在: {task_id}")
        return self._to_detail(task)

    # ---- POST /tasks/{taskId}/complete (Story4B) ----

    def complete(self, task_id: str, user_id: str) -> TaskCompleteData:
        """标记任务完成 + 即时级联（doc/04 3.5 行540）。

        事务内：
          1. 校验 task 存在 + 状态机（待执行->已完成 forward）
          2. UPDATE tasks SET status='已完成', completed_at, status_changed_at
          3. 写 status_change_log（forward, triggered_by='user'）
          4. 完成级联（task->phase->theme->goal，写 cascade 审计 + emit 事件）
          5. COMMIT

        不含后置（完成和后置脱钩，doc/01 4B 设计要点）。
        """
        task = self.task_repo.get(task_id)
        if task is None:
            raise NotFoundError(f"任务不存在: {task_id}")

        old_status = task.status
        if old_status == "已完成":
            raise ConflictError(f"任务已完成: {task_id}")
        try:
            state_machine.validate_transition("task", old_status, "已完成", None)
        except ValueError as e:
            raise BadRequestError(str(e)) from e

        now = now_utc_naive()
        task.status = "已完成"
        task.completed_at = now
        task.status_changed_at = now

        audit.log_status_change(
            self.db,
            entity_type="task",
            entity_id=task_id,
            from_status=old_status,
            to_status="已完成",
            change_type="forward",
            triggered_by="user",
        )

        # 完成级联（事务内，纯 DB <200ms）
        cascade_result = cascade.cascade_status(self.db, "task", task_id)

        self.db.commit()

        return TaskCompleteData(
            task_id=task_id,
            status="已完成",
            cascade=CascadeResult(**cascade_result),
        )

    # ---- PATCH /tasks/{taskId} (Story5 日终异议双向) ----

    def patch_status(
        self,
        task_id: str,
        status: str,
        triggered_by: str = "user",
        completed_at: datetime | None = None,
    ) -> TaskPatchStatusData:
        """日终异议双向状态变更（doc/04 §3.7 PATCH /tasks/{taskId}）。

        双向（doc/01 S5 + D18 裁决）：
          - 待执行->已完成（forward）：复用 complete 核心逻辑（validate + set + audit + 完成级联）。
          - 已完成->待执行（revert）：系统自动填默认 reason（不弹窗，D18），审计可追溯（D6）。

        事务内：DB 写 + 即时级联（<200ms）；事务后异步刷卡片（webhook 层）。
        """
        task = self.task_repo.get(task_id)
        if task is None:
            raise NotFoundError(f"任务不存在: {task_id}")

        old_status = task.status

        # ---- forward：待执行->已完成 ----
        if status == "已完成":
            if old_status == "已完成":
                raise ConflictError(f"任务已完成: {task_id}")
            try:
                state_machine.validate_transition("task", old_status, "已完成", None)
            except ValueError as e:
                raise BadRequestError(str(e)) from e

            now = completed_at if completed_at is not None else now_utc_naive()
            task.status = "已完成"
            task.completed_at = now
            task.status_changed_at = now

            audit.log_status_change(
                self.db,
                entity_type="task",
                entity_id=task_id,
                from_status=old_status,
                to_status="已完成",
                change_type="forward",
                triggered_by=triggered_by,
            )

            cascade_result = cascade.cascade_status(self.db, "task", task_id)
            self.db.commit()

            return TaskPatchStatusData(
                task_id=task_id,
                status="已完成",
                cascade=CascadeResult(**cascade_result),
            )

        # ---- revert：已完成->待执行 ----
        if status == "待执行":
            # 系统自动填默认 reason（D18 裁决：不弹窗，满足 D6 reason 必填）
            try:
                state_machine.validate_transition(
                    "task", old_status, "待执行", reason=REVERT_REASON
                )
            except ValueError as e:
                raise BadRequestError(str(e)) from e

            now = now_utc_naive()
            task.status = "待执行"
            task.completed_at = None
            task.status_changed_at = now

            audit.log_status_change(
                self.db,
                entity_type="task",
                entity_id=task_id,
                from_status=old_status,
                to_status="待执行",
                change_type="revert",
                reason=REVERT_REASON,
                triggered_by=triggered_by,
            )

            # 回退级联（事务内，纯 DB <200ms）
            revert_result = cascade.cascade_revert(self.db, task_id)
            self.db.commit()

            return TaskPatchStatusData(
                task_id=task_id,
                status="待执行",
                cascade=RevertCascadeResult(**revert_result),
            )

        raise BadRequestError(f"不支持的目标状态: {status!r}（仅 已完成/待执行）")

    # ---- POST /tasks/{taskId}/post-confirm (Story4B) ----

    def post_confirm(
        self, task_id: str, user_id: str, post_subtasks: list[PostSubtaskInput]
    ) -> PostConfirmData:
        """后置确认（doc/04 3.5 行595）：INSERT 勾选的后置子任务，可全取消。

        事务内：
          1. 校验 task 存在 + 已完成 + executor='human'（后置只对人执行任务）
          2. INSERT subtasks（type='后置', status='待执行'）；全取消则不插入
          3. COMMIT

        事务后异步（路由层 BackgroundTasks 调 trigger_post_async）：
          - opencode run 执行后置（桩，S4A 换真实现）
        """
        task = self.task_repo.get(task_id)
        if task is None:
            raise NotFoundError(f"任务不存在: {task_id}")

        if task.status != "已完成":
            raise BadRequestError(f"后置确认要求任务已完成，当前状态: {task.status}")

        if task.executor != "human":
            raise BadRequestError(f"后置只对人执行任务，当前 executor: {task.executor!r}")

        count = 0
        if post_subtasks:
            sort_base = self.subtask_repo.next_sort_order(task_id)
            for idx, ps in enumerate(post_subtasks):
                sub = Subtask(
                    id=str(uuid4()),
                    task_id=task_id,
                    sort_order=sort_base + idx,
                    name=ps.name,
                    description=ps.description,
                    type="后置",
                    status="待执行",
                )
                self.subtask_repo.create(sub)
                count += 1

        self.db.commit()

        return PostConfirmData(
            task_id=task_id,
            post_subtask_count=count,
            async_triggered=count > 0,
        )

    @staticmethod
    def trigger_post_async(task_id: str) -> None:
        """事务后异步执行后置子任务（独立 session，BackgroundTasks 调用）。

        S4B 桩：调 OpenCodeClient.dispatch_post_subtasks（no-op + 日志）。
        S4A 换成真 opencode run HTTP dispatch。失败非阻塞（doc/01 4B 设计要点）。
        """
        db = SessionLocal()
        try:
            post_subs = list(
                db.scalars(
                    select(Subtask).where(Subtask.task_id == task_id, Subtask.type == "后置")
                )
            )
            if not post_subs:
                return
            client = OpenCodeClient()
            client.dispatch_post_subtasks(
                [{"id": s.id, "name": s.name, "task_id": s.task_id} for s in post_subs]
            )
        except Exception:
            logger.exception("post trigger_async 失败: %s", task_id)
        finally:
            db.close()

    # ---- subtask CRUD（POST/GET/PATCH /subtasks）----

    def create_subtask(self, req: SubtaskCreateRequest) -> SubtaskData:
        """创建子任务（前置/后置，由 pm-subtask 生成后调用）。

        前置/后置只服务人执行任务（doc/02 2.5）：校验 task.executor='human'，
        与 post_confirm 的约束一致，防止绕过 post_confirm 直连此端点。
        """
        task = self.task_repo.get(req.task_id)
        if task is None:
            raise NotFoundError(f"任务不存在: {req.task_id}")
        if task.executor != "human":
            raise BadRequestError(f"子任务只服务人执行任务，当前 executor: {task.executor!r}")
        if req.type not in ("前置", "后置"):
            raise BadRequestError(f"子任务类型非法: {req.type!r}（仅 前置/后置）")
        sort_order = self.subtask_repo.next_sort_order(req.task_id)
        sub = Subtask(
            id=str(uuid4()),
            task_id=req.task_id,
            sort_order=sort_order,
            name=req.name,
            description=req.description,
            type=req.type,
            status="待执行",
        )
        self.subtask_repo.create(sub)
        self.db.commit()
        return self._to_subtask_data(sub)

    def get_subtask(self, subtask_id: str) -> SubtaskData:
        sub = self.subtask_repo.get(subtask_id)
        if sub is None:
            raise NotFoundError(f"子任务不存在: {subtask_id}")
        return self._to_subtask_data(sub)

    def patch_subtask(self, subtask_id: str, req: SubtaskPatchRequest) -> SubtaskData:
        """更新子任务状态（异步执行完成后回调）。

        状态流转校验（最小防御，doc 未为 subtask 定义正式状态机）：
          - 正向流转允许：待执行->进行中->已完成 / ->失败
          - 禁止逆向：已完成/失败/进行中 -> 待执行（防止数据不一致）
        """
        sub = self.subtask_repo.get(subtask_id)
        if sub is None:
            raise NotFoundError(f"子任务不存在: {subtask_id}")
        if req.status is not None:
            if req.status not in ("待执行", "进行中", "已完成", "失败"):
                raise BadRequestError(f"子任务状态非法: {req.status!r}")
            # 禁止逆向流转到待执行（已完成/失败/进行中 -> 待执行）
            if req.status == "待执行" and sub.status in ("进行中", "已完成", "失败"):
                raise BadRequestError(f"子任务不可从 {sub.status!r} 回退到 '待执行'")
            if req.status == "已完成":
                sub.completed_at = now_utc_naive()
            sub.status = req.status
        if req.output_path is not None:
            sub.output_path = req.output_path
        self.db.commit()
        return self._to_subtask_data(sub)

    # ---- POST /tasks/{taskId}/confirm-complete (Story4A) ----

    def confirm_complete(self, task_id: str, user_id: str) -> ConfirmCompleteData:
        """4A 人工确认完成。3 次重试不通过，用户手动接管后调用。

        事务（doc/04 行588）：
          1. UPDATE tasks SET status='已完成', completed_at=NOW()
          2. 写 status_change_log（forward, triggered_by='user'）
          3. 即时级联（cascade.cascade_status, S4B 实现完成链）
          4. COMMIT

        事务后异步（doc/04 行593）：
          5. 检测该工作空间是否还有待执行智能体任务
             是 -> 重启 opencode serve（不同端口）接管
             否 -> 不启动
        """
        task = self.task_repo.get(task_id)
        if task is None:
            raise NotFoundError(f"任务不存在: {task_id}")
        if task.status == "已完成":
            raise BadRequestError(f"任务已完成: {task_id}")

        old_status = task.status
        # 状态机校验（task forward，S4B 扩展，本文件调用接口）
        state_machine.validate_transition("task", old_status, "已完成", None)

        # 1. UPDATE task
        now = now_utc_naive()
        task.status = "已完成"
        task.completed_at = now
        task.status_changed_at = now

        # 2. 审计
        audit.log_status_change(
            self.db,
            entity_type="task",
            entity_id=task_id,
            from_status=old_status,
            to_status="已完成",
            change_type="forward",
            triggered_by="user",
        )

        # 3. 即时级联（完成级联 S4B 实现，本文件调用接口）
        cascade.cascade_status(self.db, "task", task_id)

        # 4. COMMIT
        self.db.commit()

        # 发阶段完成事件（S8 接 EventBus，当前桩 no-op）
        emit({"type": "task_completed", "entity_id": task_id})

        # 5. 异步：检测后续智能体任务 + 重启 opencode serve
        next_agent_task = self._find_next_agent_task(task)
        opencode_restarted = False
        if next_agent_task:
            opencode_restarted = self._restart_opencode(task, next_agent_task) > 0

        return ConfirmCompleteData(
            task_id=task_id,
            status="已完成",
            cascade=CascadeResult(phase_completed=self._check_phase_completed(task)),
            opencode_restarted=opencode_restarted,
            next_agent_task=next_agent_task.id if next_agent_task else None,
        )

    # ---- POST /tasks/{taskId}/output/confirm (Story4A) ----

    def output_confirm(
        self, task_id: str, user_id: str, workspace_progress_ids: list[str]
    ) -> OutputConfirmData:
        """验收通过智能体产出。即时级联。

        事务（doc/04 行646）：
          1. UPDATE tasks SET status='已完成', completed_at=NOW()
          2. UPDATE subtasks（相关前置）SET status='已完成'
          3. 写 status_change_log
          4. 即时级联
          5. COMMIT
        """
        task = self.task_repo.get(task_id)
        if task is None:
            raise NotFoundError(f"任务不存在: {task_id}")
        if task.status == "已完成":
            raise BadRequestError(f"任务已完成: {task_id}")

        old_status = task.status
        state_machine.validate_transition("task", old_status, "已完成", None)

        # 1. UPDATE task
        now = now_utc_naive()
        task.status = "已完成"
        task.completed_at = now
        task.status_changed_at = now

        # 2. UPDATE 相关前置子任务为已完成
        pre_subs = self.subtask_repo.list_by_task(task_id)
        for sub in pre_subs:
            if sub.type == "前置" and sub.status != "已完成":
                sub.status = "已完成"
                sub.completed_at = now

        # 3. 审计
        audit.log_status_change(
            self.db,
            entity_type="task",
            entity_id=task_id,
            from_status=old_status,
            to_status="已完成",
            change_type="forward",
            triggered_by="user",
        )

        # 4. 即时级联
        cascade.cascade_status(self.db, "task", task_id)

        # 5. COMMIT
        self.db.commit()

        emit({"type": "task_completed", "entity_id": task_id})

        return OutputConfirmData(
            task_id=task_id,
            status="已完成",
            cascade=CascadeResult(phase_completed=self._check_phase_completed(task)),
        )

    # ---- POST /tasks/{taskId}/output/reject (Story4A) ----

    def output_reject(self, task_id: str, user_id: str, feedback: str) -> OutputRejectData:
        """退回智能体产出，重试或通知。

        事务内（铁律 §3#3/#4）：仅更新 retry_count + COMMIT。
        事务后异步（由路由层 BackgroundTasks 调 trigger_reject_async）：
          - retry 路径：dispatch_task + 重设 Redis 超时
          - manual_intervention 路径：opencode shutdown + 飞书通知

        逻辑（doc/04 行654, doc/06 步骤8）：
          - retry_count < 3：retry_count+=1 -> action='retry'
          - retry_count >= 3：不改状态 -> action='manual_intervention'

        3 次不通过不改 task 状态（doc/01 4A要点）。
        """
        task = self.task_repo.get(task_id)
        if task is None:
            raise NotFoundError(f"任务不存在: {task_id}")

        if task.retry_count < MAX_RETRY:
            # 重试路径：事务内仅更新 retry_count
            task.retry_count += 1
            self.db.commit()
            return OutputRejectData(
                task_id=task_id,
                retry_count=task.retry_count,
                max_retry=MAX_RETRY,
                action="retry",
                async_triggered=True,
            )
        else:
            # 超次路径：3 次不通过不改状态，事务内无需写 DB
            workspace = self._get_workspace_for_task(task)
            workspace_path = workspace.path if workspace else None
            return OutputRejectData(
                task_id=task_id,
                retry_count=task.retry_count,
                max_retry=MAX_RETRY,
                action="manual_intervention",
                opencode_stopped=True,
                workspace_path=workspace_path,
            )

    @staticmethod
    def trigger_reject_async(task_id: str, feedback: str) -> None:
        """output_reject 事务后异步触发（独立 session，BackgroundTasks 调用）。

        铁律 §3#3/#4：HTTP/Redis/feishu 均在事务后异步，满足飞书 3 秒回调。

        retry 路径：dispatch_task + 重设 Redis 超时。
        manual_intervention 路径：opencode shutdown + 飞书通知。
        """
        db = SessionLocal()
        try:
            task = db.get(Task, task_id)
            if task is None:
                return

            if task.retry_count < MAX_RETRY:
                # retry 路径：重新下发任务 + 重设超时
                svc = TaskAppSvc(db)
                svc._retry_dispatch(task, feedback)
            else:
                # manual_intervention 路径：shutdown + 飞书通知
                svc = TaskAppSvc(db)
                workspace = svc._get_workspace_for_task(task)
                workspace_path = workspace.path if workspace else None
                workspace_id = svc._get_workspace_id_for_task(task)
                if workspace_id:
                    svc.opencode.shutdown(workspace_id)
                try:
                    svc.feishu.send_text(
                        "chat_id_placeholder",
                        f"⚠️ 智能体任务多次验收不通过\n"
                        f"任务：{task.name}\n"
                        f"工作空间路径：{workspace_path}\n"
                        f"反馈：{feedback}\n"
                        f"请手动启动 opencode 处理。",
                    )
                except Exception:
                    logger.exception("发送 manual_intervention 通知失败: task=%s", task.id)
        except Exception:
            logger.exception("trigger_reject_async 失败: task=%s", task_id)
        finally:
            db.close()

    # ---- POST /api/callback/opencode/output ----

    def record_output(
        self, task_id: str, workspace_id: str, outputs: list[dict]
    ) -> RecordOutputData:
        """记录 OpenCode 产出回调。

        事务（doc/04 §3.12, doc/06 步骤5）：
          1. INSERT workspace_progress（每个产出文件一条记录）
          2. COMMIT
          3. 事务后异步：DEL Redis 超时 + 发验收卡片 + 发送产出文件到飞书
        """
        today = now_utc_naive().date()
        count = 0
        for output in outputs:
            wp = WorkspaceProgress(
                id=str(uuid4()),
                workspace_id=workspace_id,
                date=today,
                task_id=task_id,
                file_path=output["file_path"],
                file_type=output["file_type"],
            )
            self.wp_repo.create(wp)
            count += 1

        self.db.commit()

        # 事务后异步：DEL Redis 超时 + 发验收卡片 + 发送文件
        self._trigger_output_async(task_id, workspace_id, outputs)

        return RecordOutputData(received=True, progress_count=count)

    # ---- POST /api/callback/opencode/timeout (Story4A) ----

    def handle_timeout(self, task_id: str, workspace_id: str) -> TimeoutAlertData:
        """Redis 超时告警回调（KeyExpirationEvent 触发）。

        doc/02 §2.17：2h 未回调 -> 飞书通知"智能体执行超时"。
        """
        # 飞书通知（事务外 IO）
        try:
            self.feishu.send_text(
                "chat_id_placeholder",
                f"⚠️ 智能体执行超时\n任务 ID: {task_id}\n工作空间: {workspace_id}\n"
                "已过 2 小时未收到回调，请检查。",
            )
        except Exception:
            logger.exception("超时告警飞书通知失败: task=%s", task_id)

        return TimeoutAlertData(alert_sent=True)

    # ---- 辅助方法（Story4A）----

    @staticmethod
    def refresh_summary_card_async(task_id: str, message_id: str, daily_id: str) -> None:
        """事务后异步刷新日终总结卡片（独立 session，BackgroundTasks 调用）。

        异议状态变更后，重新查询统计数据 -> 构建新卡片 -> 调 feishu update_card 更新消息。
        铁律 §3#3/#4：HTTP 事务后异步，满足飞书 3 秒回调。
        """
        db = SessionLocal()
        try:
            from app.models.daily_record import DailyRecord
            from app.services.daily_app_svc import DailyAppSvc

            # 查 daily_record 的日期，用该日期重新统计
            daily = db.get(DailyRecord, daily_id) if daily_id else None
            date_ = daily.date if daily else None
            summary = DailyAppSvc(db).generate_summary("system", date_)
            card = build_daily_summary_card(
                daily_id=summary.daily_id or daily_id,
                date_str=summary.date.isoformat(),
                completed_tasks=[
                    {"task_id": t.task_id, "name": t.name, "theme_name": t.theme_name}
                    for t in summary.completed_tasks
                ],
                incomplete_tasks=[
                    {"task_id": t.task_id, "name": t.name, "theme_name": t.theme_name}
                    for t in summary.incomplete_tasks
                ],
                phase_health=[
                    {
                        "name": p.name,
                        "completed": p.completed,
                        "total": p.total,
                        "rate": p.rate,
                        "status": p.status,
                    }
                    for p in summary.phase_health
                ],
            )
            FeishuClient().update_card(message_id, card)
        except Exception:
            logger.exception("refresh_summary_card_async 失败: task=%s", task_id)
        finally:
            db.close()

    def _to_detail(self, task: Task) -> TaskDetailData:
        return TaskDetailData(
            task_id=task.id,
            name=task.name,
            description=task.description,
            status=task.status,
            executor=task.executor,
            phase_id=task.phase_id,
            sort_order=task.sort_order,
            has_subtask=task.has_subtask,
            retry_count=task.retry_count,
            completed_at=task.completed_at,
        )

    def _check_phase_completed(self, task: Task) -> bool:
        """检查任务所属阶段是否全部完成（即时级联后验证）。"""
        from app.models.phase import Phase

        phase = self.db.get(Phase, task.phase_id)
        return phase is not None and phase.status == "已完成"

    def _find_next_agent_task(self, completed_task: Task) -> Task | None:
        """查找该工作空间下下一个待执行的智能体任务。

        查同 phase 下 executor='agent' 且 status='待执行' 的任务。
        """
        tasks = self.task_repo.list_by_phase(completed_task.phase_id)
        for t in tasks:
            if t.id != completed_task.id and t.status == "待执行" and t.executor == "agent":
                return t
        return None

    def _restart_opencode(self, completed_task: Task, next_task: Task) -> int:
        """重启 opencode serve（不同端口）接管后续智能体任务。

        doc/01 4A："/pm 确认完成"后系统重新启动 opencode serve（不同端口）接管。
        先 shutdown 旧进程（如存在），再 start_agent_serve 新进程。
        """
        workspace_id = self._get_workspace_id_for_task(completed_task)
        if workspace_id is None:
            return -1
        # 先停旧进程（best effort）
        self.opencode.shutdown(workspace_id)
        # 再启新进程（分配新端口）
        task_dict = {
            "task_id": next_task.id,
            "name": next_task.name,
            "phase_id": next_task.phase_id,
        }
        return self.opencode.start_agent_serve(workspace_id, task_dict)

    def _retry_dispatch(self, task: Task, feedback: str) -> None:
        """重试：重新 dispatch_task + 重设 Redis 超时。

        事务后异步调用（IO 操作）。
        """
        workspace_id = self._get_workspace_id_for_task(task)
        if workspace_id is None:
            return

        # 查 opencode serve 端口
        ap = self.agent_repo.get_running_by_workspace(workspace_id)
        if ap is None:
            logger.warning("retry_dispatch: 无 running 进程 ws=%s", workspace_id)
            return

        try:
            self.opencode.dispatch_task(
                workspace_id,
                {"task_id": task.id, "name": task.name, "feedback": feedback},
                ap.port,
            )
            # 重设 Redis 超时
            set_task_timeout(task.id, workspace_id)
        except Exception:
            logger.exception("retry_dispatch 失败: task=%s", task.id)

    def _get_workspace_id_for_task(self, task: Task) -> str | None:
        """通过 task -> phase -> theme -> workspace 查找工作空间 ID。"""
        from app.models.phase import Phase
        from app.models.theme import Theme

        phase = self.db.get(Phase, task.phase_id)
        if phase is None:
            return None
        theme = self.db.get(Theme, phase.theme_id)
        if theme is None:
            return None
        ws = self.workspace_repo.get_by_theme(theme.id)
        return ws.id if ws else None

    def _get_workspace_for_task(self, task: Task) -> Workspace | None:
        """通过 task -> phase -> theme -> workspace 查找工作空间。"""
        from app.models.phase import Phase
        from app.models.theme import Theme

        phase = self.db.get(Phase, task.phase_id)
        if phase is None:
            return None
        theme = self.db.get(Theme, phase.theme_id)
        if theme is None:
            return None
        return self.workspace_repo.get_by_theme(theme.id)

    def _trigger_output_async(self, task_id: str, workspace_id: str, outputs: list[dict]) -> None:
        """事务后异步：DEL Redis 超时 + 发验收卡片 + 发送产出文件到飞书。

        doc/06 步骤5-6：
          - DEL task_timeout:{task_id}
          - 发验收卡片（模板填充，无 LLM）：任务名 + 产出文件名列表 + 验收通过/需要修改按钮
          - 逐个发送产出文件到飞书
        """
        # DEL Redis 超时
        try:
            del_task_timeout(task_id)
        except Exception:
            logger.warning("DEL Redis 超时失败: task=%s", task_id)

        # 查任务名
        task = self.task_repo.get(task_id)
        task_name = task.name if task else task_id
        file_paths = [o["file_path"] for o in outputs]

        # 发验收卡片
        try:
            card = build_verification_card(task_id, task_name, file_paths)
            self.feishu.send_card("chat_id_placeholder", card)
        except Exception:
            logger.exception("发送验收卡片失败: task=%s", task_id)

        # 逐个发送产出文件
        for fp in file_paths:
            try:
                self.feishu.send_file("chat_id_placeholder", fp)
            except Exception:
                logger.exception("发送产出文件失败: %s", fp)

    # ---- 转换辅助（Story4B）----

    @staticmethod
    def _to_subtask_data(sub: Subtask) -> SubtaskData:
        return SubtaskData(
            subtask_id=sub.id,
            task_id=sub.task_id,
            name=sub.name,
            description=sub.description,
            type=sub.type,
            status=sub.status,
            sort_order=sub.sort_order,
            output_path=sub.output_path,
            completed_at=sub.completed_at,
        )
