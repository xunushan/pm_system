"""BoardAppSvc：H5 看板编辑（Story9，入口 C）。

doc/03 line 262「BoardAppSvc 处理 H5 编辑：校验状态机 + 回退 reason -> 落库 +
status_change_log -> 即时级联」。

方法：
  - update_fields：字段编辑（名称/描述/deadline/executor）+ 增删任务（new_tasks）+ 阶段排序
  - change_status：状态变更（暂停填 reason / 恢复 / 回退填 reason + 即时级联）
  - delete_task：物理删除任务（+ 关联记录）

铁律（CLAUDE.md §3）：
  - #1 Service 不调 LLM：纯确定性校验 + 状态机 + 级联。
  - #2 board 是 H5 API（入口 C），直接进执行态事务。
  - #3 即时级联在事务内（revert 级联 <200ms）；事务内禁 IO。
  - #5 DB 唯一真相源：H5 编辑落库，无反向同步。
  - #7 状态机：pause/resume/revert 写 status_change_log；revert/pause 必填 reason。
  - #8.9 pause 不占名额（已暂停不纳入计划）；board 不提供 forward（走 activate）。
  - §11 先搜后建：复用 state_machine / cascade_revert_entity / audit，禁重写。
"""

from datetime import date
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core import audit, cascade, state_machine
from app.core.exceptions import BadRequestError, NotFoundError
from app.core.times import now_utc_naive
from app.models.daily_task import DailyTask
from app.models.goal import Goal
from app.models.phase import Phase
from app.models.subtask import Subtask
from app.models.task import Task
from app.models.theme import Theme
from app.models.workspace_progress import WorkspaceProgress
from app.schemas.board import (
    BoardCascadeResult,
    BoardStatusData,
    BoardUpdateData,
    TaskDeleteData,
)

# 各 entity 允许编辑的字段（managed/path 不可改，doc/01 S9 line 717）
_EDITABLE_FIELDS: dict[str, set[str]] = {
    "goal": {"name", "description"},
    "theme": {"name", "description"},
    "phase": {"name", "description", "deadline"},
    "task": {"name", "description", "executor"},
}

# board 不提供 forward 激活（走 schedules/activate，带工作空间初始化）
_FORWARD_NOT_ALLOWED = "board 不提供 forward 激活，请走 /schedules/activate 端点"

# 新增任务时 executor 校验值
_VALID_EXECUTORS = {None, "human", "agent"}


class BoardAppSvc:
    """H5 看板编辑服务（Story9）。

    update_fields / change_status / delete_task。
    """

    # 实体类型 -> ORM 类 的映射（统一查表入口）
    _ENTITY_MODELS = {
        "goal": Goal,
        "theme": Theme,
        "phase": Phase,
        "task": Task,
    }

    def __init__(self, db: Session) -> None:
        self.db = db

    # ---- PUT /board/{entity}/{id} ----

    def update_fields(self, entity: str, entity_id: str, fields: dict) -> BoardUpdateData:
        """H5 字段编辑（doc/04 §3.12 PUT /board/{entity}/{id}）。

        事务内落库，无级联（字段编辑不触发级联，除非 status 变更走 change_status）。
        特殊字段：
          - theme.phase_orders：阶段重排（更新 phases.sort_order）
          - phase.new_tasks：新增任务（INSERT tasks）
        """
        model = self._ENTITY_MODELS.get(entity)
        if model is None:
            raise BadRequestError(f"不支持的实体类型: {entity!r}（仅 goal/theme/phase/task）")

        obj = self.db.get(model, entity_id)
        if obj is None:
            raise NotFoundError(f"{entity} 不存在: {entity_id}")

        allowed = _EDITABLE_FIELDS[entity]
        updated_fields: list[str] = []
        created_task_ids: list[str] = []

        for key, value in fields.items():
            if key == "phase_orders" and entity == "theme":
                self._apply_phase_orders(obj, value)
                updated_fields.append("phase_orders")
                continue
            if key == "new_tasks" and entity == "phase":
                ids = self._create_new_tasks(obj, value)
                created_task_ids.extend(ids)
                updated_fields.append("new_tasks")
                continue
            if key not in allowed:
                raise BadRequestError(
                    f"字段 {key!r} 不可编辑（entity={entity}，允许: {sorted(allowed)}）"
                )
            if key == "executor" and value not in _VALID_EXECUTORS:
                raise BadRequestError(f"executor 非法: {value!r}（仅 human/agent/null）")
            if key == "deadline" and value is not None:
                value = date.fromisoformat(value) if isinstance(value, str) else value
            setattr(obj, key, value)
            updated_fields.append(key)

        self.db.commit()

        return BoardUpdateData(
            entity=entity,
            id=entity_id,
            updated_fields=updated_fields,
            created_task_ids=created_task_ids or None,
        )

    def _apply_phase_orders(self, theme: Theme, phase_orders: list[dict]) -> None:
        """阶段重排：更新 phases.sort_order（doc/01 S9 场景3）。

        要求 phase_orders 包含该专题下全部 phase（避免部分重排导致
        UNIQUE(theme_id, sort_order) 约束冲突或遗漏）。
        """
        if not isinstance(phase_orders, list):
            raise BadRequestError("phase_orders 必须是列表")
        items: list[tuple[str, int]] = []
        submitted_ids: set[str] = set()
        for item in phase_orders:
            phase_id = item.get("phase_id") if isinstance(item, dict) else None
            sort_order = item.get("sort_order") if isinstance(item, dict) else None
            if not phase_id or sort_order is None:
                raise BadRequestError("phase_orders 每项需含 phase_id 和 sort_order")
            phase = self.db.get(Phase, phase_id)
            if phase is None or phase.theme_id != theme.id:
                raise BadRequestError(f"阶段不属于该专题或不存在: {phase_id}")
            if phase_id in submitted_ids:
                raise BadRequestError(f"phase_orders 含重复 phase_id: {phase_id}")
            submitted_ids.add(phase_id)
            items.append((phase_id, sort_order))

        # 校验：phase_orders 必须包含该专题下全部 phase（避免部分重排冲突/遗漏）
        all_phase_ids = {
            p.id for p in self.db.scalars(select(Phase).where(Phase.theme_id == theme.id))
        }
        if submitted_ids != all_phase_ids:
            missing = all_phase_ids - submitted_ids
            raise BadRequestError(
                f"阶段排序需包含该专题下全部阶段（缺少 {len(missing)} 个: {sorted(missing)}）"
            )

        # 两阶段更新避免 UNIQUE(theme_id, sort_order) 中间冲突：
        # 先偏移到临时大值，再设最终值
        OFFSET = 10000
        for phase_id, _ in items:
            phase = self.db.get(Phase, phase_id)
            phase.sort_order += OFFSET
        self.db.flush()
        for phase_id, sort_order in items:
            phase = self.db.get(Phase, phase_id)
            phase.sort_order = sort_order

    def _create_new_tasks(self, phase: Phase, new_tasks: list[dict]) -> list[str]:
        """新增任务到已激活阶段（doc/01 S9 场景2）。

        sort_order 自动分配（当前 phase 下最大 sort_order + 1 递增）。
        """
        if not isinstance(new_tasks, list):
            raise BadRequestError("new_tasks 必须是列表")
        # 查当前 phase 下最大 sort_order
        existing = list(
            self.db.scalars(select(Task).where(Task.phase_id == phase.id).order_by(Task.sort_order))
        )
        next_sort = max((t.sort_order for t in existing), default=0) + 1
        created_ids: list[str] = []
        for item in new_tasks:
            name = item.get("name") if isinstance(item, dict) else None
            if not name:
                raise BadRequestError("new_tasks 每项需含 name")
            executor = item.get("executor")
            if executor not in _VALID_EXECUTORS:
                raise BadRequestError(f"executor 非法: {executor!r}（仅 human/agent/null）")
            task = Task(
                id=str(uuid4()),
                phase_id=phase.id,
                sort_order=next_sort,
                name=name,
                description=item.get("description"),
                status="待执行",
                executor=executor,
            )
            self.db.add(task)
            self.db.flush()
            created_ids.append(task.id)
            next_sort += 1
        return created_ids

    # ---- POST /board/{entity}/{id}/status ----

    def change_status(
        self,
        entity: str,
        entity_id: str,
        to_status: str,
        reason: str | None = None,
        triggered_by: str = "user",
    ) -> BoardStatusData:
        """H5 状态变更（doc/04 §3.12 POST /board/{entity}/{id}/status）。

        事务内（doc/04 line 877）：
          1. 校验状态机（from->to 是否允许）
          2. 校验 reason（revert/pause 必填 1005；resume 不填）
          3. UPDATE status + status_changed_at（+ completed_at/paused_at）
          4. 写 status_change_log
          5. 即时重算级联（revert 调 cascade_revert_entity；pause/resume 无级联）
          6. COMMIT

        board 不提供 forward（forward 走 schedules/activate）。
        """
        model = self._ENTITY_MODELS.get(entity)
        if model is None:
            raise BadRequestError(f"不支持的实体类型: {entity!r}（仅 goal/theme/phase/task）")

        obj = self.db.get(model, entity_id)
        if obj is None:
            raise NotFoundError(f"{entity} 不存在: {entity_id}")

        from_status = obj.status

        # 判断变更类型
        change_type = state_machine.get_change_type(entity, from_status, to_status)
        if change_type is None:
            raise BadRequestError(f"非法状态流转: {entity} {from_status!r} -> {to_status!r}")
        if change_type == "forward":
            raise BadRequestError(_FORWARD_NOT_ALLOWED)

        # 校验状态机 + reason（ReasonRequiredError 1005 由 state_machine 抛出）
        try:
            state_machine.validate_transition(entity, from_status, to_status, reason)
        except ValueError as e:
            raise BadRequestError(str(e)) from e

        # UPDATE status + 时间戳
        now = now_utc_naive()
        obj.status = to_status
        obj.status_changed_at = now

        # 清理/设置时间戳列（phase/task 有 completed_at/paused_at；goal/theme 无）
        if hasattr(obj, "completed_at"):
            if change_type == "revert":
                obj.completed_at = None
        if hasattr(obj, "paused_at"):
            if change_type == "pause":
                obj.paused_at = now
            elif change_type == "resume":
                obj.paused_at = None

        # 写 status_change_log（change_type 由 state_machine 定）
        audit.log_status_change(
            self.db,
            entity_type=entity,
            entity_id=entity_id,
            from_status=from_status,
            to_status=to_status,
            change_type=change_type,
            triggered_by=triggered_by,
            reason=reason,
        )

        # 即时级联（仅 revert，pause/resume 无级联）
        cascade_data = {
            "phase_reverted": False,
            "theme_reverted": False,
            "goal_reverted": False,
            "phase_id": None,
            "theme_id": None,
            "goal_id": None,
        }
        if change_type == "revert":
            cascade_data = cascade.cascade_revert_entity(self.db, entity, entity_id)

        self.db.commit()

        return BoardStatusData(
            entity=entity,
            id=entity_id,
            from_status=from_status,
            to_status=to_status,
            change_type=change_type,
            cascade=BoardCascadeResult(**cascade_data),
            audit_logged=True,
        )

    # ---- DELETE /tasks/{taskId} ----

    def delete_task(self, task_id: str) -> TaskDeleteData:
        """物理删除任务（doc/04 line 534，v2.0 新增）。

        事务内：
          1. 校验 task 存在
          2. 删除关联记录（daily_tasks / subtasks / workspace_progress）
          3. DELETE task
          4. COMMIT

        不触发完成级联（物理删除是结构调整，非完成动作；完成级联由 task 完成 trigger）。
        """
        task = self.db.get(Task, task_id)
        if task is None:
            raise NotFoundError(f"任务不存在: {task_id}")

        # 删除关联记录（FK 无 CASCADE，手动清理；PRAGMA foreign_keys=ON）
        self.db.execute(delete(DailyTask).where(DailyTask.task_id == task_id))
        self.db.execute(delete(Subtask).where(Subtask.task_id == task_id))
        self.db.execute(delete(WorkspaceProgress).where(WorkspaceProgress.task_id == task_id))

        self.db.delete(task)
        self.db.commit()

        return TaskDeleteData(task_id=task_id)
