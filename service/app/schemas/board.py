"""H5 看板编辑请求/响应模型。详见《服务API文档 v2.0》3.12（Story9）。

PUT  /board/{entity}/{id}        字段编辑（名称/描述/deadline/executor）+ 增删任务 + 阶段排序
POST /board/{entity}/{id}/status 状态变更（暂停填 reason / 恢复 / 回退填 reason + 即时级联）
"""

from typing import Any

from pydantic import BaseModel, Field


class BoardUpdateRequest(BaseModel):
    """PUT /board/{entity}/{id} 请求。

    fields 支持的键（按 entity 不同）：
      goal:  name, description
      theme: name, description, phase_orders（阶段重排 [{phase_id, sort_order}]）
      phase: name, description, deadline, new_tasks（新增任务 [{name, description?, executor?}]）
      task:  name, description, executor

    managed/path 不可改（激活后在 Story2 设置，doc/01 S9 line 717）。
    任务排序不支持（交给 pm-daily，doc/01 S9 line 715）。
    """

    fields: dict[str, Any] = Field(default_factory=dict)


class NewTaskInfo(BaseModel):
    """新增任务信息（PUT board/phase/{id} 的 fields.new_tasks 元素）。"""

    name: str
    description: str | None = None
    executor: str | None = None


class PhaseOrderItem(BaseModel):
    """阶段重排项（PUT board/theme/{id} 的 fields.phase_orders 元素）。"""

    phase_id: str
    sort_order: int


class BoardUpdateData(BaseModel):
    """PUT /board/{entity}/{id} 响应。"""

    entity: str
    id: str
    updated_fields: list[str] = Field(default_factory=list)
    created_task_ids: list[str] | None = None


# ---- POST /board/{entity}/{id}/status ----


class BoardStatusRequest(BaseModel):
    """POST /board/{entity}/{id}/status 请求（状态变更：暂停/恢复/回退）。

    board 不提供 forward 激活（走 schedules/activate，带工作空间初始化）。
    """

    to_status: str
    reason: str | None = None
    triggered_by: str = "user"


class BoardCascadeResult(BaseModel):
    """board 状态变更级联结果（revert 可能拉回上级已完成实体）。

    pause/resume 无级联（不占名额/不纳入计划，resume 重新纳入）。
    """

    phase_reverted: bool = False
    phase_id: str | None = None
    theme_reverted: bool = False
    theme_id: str | None = None
    goal_reverted: bool = False
    goal_id: str | None = None


class BoardStatusData(BaseModel):
    """POST /board/{entity}/{id}/status 响应。"""

    entity: str
    id: str
    from_status: str
    to_status: str
    change_type: str
    cascade: BoardCascadeResult
    audit_logged: bool = True


# ---- DELETE /tasks/{taskId} ----


class TaskDeleteData(BaseModel):
    """DELETE /tasks/{taskId} 响应。"""

    task_id: str
    deleted: bool = True
