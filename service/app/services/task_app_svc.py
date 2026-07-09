"""TaskAppSvc：人完成任务（Story4B 核心服务）。

两个核心方法：
  - complete：标记任务完成 + 即时级联（完成和后置脱钩，不含后置）。
  - post_confirm：后置确认（INSERT 勾选的后置子任务，可全取消）+ 事务后异步执行。

铁律（CLAUDE.md §3）：
  - Service 不调 LLM（§3#1）：complete 只标记完成+级联；后置内容由 pm-subtask Skill 生成。
  - 事务内禁 IO/HTTP（§3#3）：opencode dispatch 事务后异步。
  - 即时级联在事务内（§3#3）：完成级联在 commit 前。
  - 后置脱钩（§3#9）：complete 即时级联，后置可全取消。
  - executor 规划态不填（§3#8）：complete 不改 executor。

另含 subtask CRUD（POST/GET/PATCH），供 pm-subtask Skill 与异步回调使用。
confirm-complete / output 端点属 Story4A，本文件不实现。
"""

import logging
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clients.opencode import OpenCodeClient
from app.core import audit, cascade, state_machine
from app.core.exceptions import BadRequestError, ConflictError, NotFoundError
from app.core.times import now_utc_naive
from app.db.session import SessionLocal
from app.models.subtask import Subtask
from app.models.task import Task
from app.repositories.subtask import SubtaskRepository
from app.repositories.task import TaskRepository
from app.schemas.subtask import SubtaskCreateRequest, SubtaskData, SubtaskPatchRequest
from app.schemas.task import (
    CascadeResult,
    PostConfirmData,
    PostSubtaskInput,
    TaskCompleteData,
    TaskDetail,
)

logger = logging.getLogger(__name__)


class TaskAppSvc:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.task_repo = TaskRepository(db)
        self.subtask_repo = SubtaskRepository(db)
        self.opencode = OpenCodeClient()

    # ---- POST /tasks/{taskId}/complete ----

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

    # ---- POST /tasks/{taskId}/post-confirm ----

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

    # ---- GET /tasks/{taskId} ----

    def get_task(self, task_id: str) -> TaskDetail:
        task = self.task_repo.get(task_id)
        if task is None:
            raise NotFoundError(f"任务不存在: {task_id}")
        return self._to_task_detail(task)

    # ---- subtask CRUD（POST/GET/PATCH /subtasks）----

    def create_subtask(self, req: SubtaskCreateRequest) -> SubtaskData:
        """创建子任务（前置/后置，由 pm-subtask 生成后调用）。"""
        task = self.task_repo.get(req.task_id)
        if task is None:
            raise NotFoundError(f"任务不存在: {req.task_id}")
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
        """更新子任务状态（异步执行完成后回调）。"""
        sub = self.subtask_repo.get(subtask_id)
        if sub is None:
            raise NotFoundError(f"子任务不存在: {subtask_id}")
        if req.status is not None:
            if req.status not in ("待执行", "进行中", "已完成", "失败"):
                raise BadRequestError(f"子任务状态非法: {req.status!r}")
            if req.status == "已完成":
                sub.completed_at = now_utc_naive()
            sub.status = req.status
        if req.output_path is not None:
            sub.output_path = req.output_path
        self.db.commit()
        return self._to_subtask_data(sub)

    # ---- 转换辅助 ----

    @staticmethod
    def _to_task_detail(task: Task) -> TaskDetail:
        return TaskDetail(
            task_id=task.id,
            name=task.name,
            description=task.description,
            status=task.status,
            executor=task.executor,
            phase_id=task.phase_id,
            sort_order=task.sort_order,
            has_subtask=task.has_subtask,
            completed_at=task.completed_at,
        )

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
