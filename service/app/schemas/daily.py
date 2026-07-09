"""今日计划请求/响应模型。详见《服务API文档 v2.0》3.4。

GET  /daily/plans/pool   今日任务池预查询（只读，供 pm-daily LLM 决策）
POST /daily/confirm       确认今日计划（任务勾选+前置勾选 -> INSERT 3 表 + 异步执行）
"""

from datetime import date

from pydantic import BaseModel, Field

# ---- GET /daily/plans/pool 响应 ----


class YesterdayCompletedTask(BaseModel):
    task_id: str
    name: str
    phase_name: str


class ActivePhaseInfo(BaseModel):
    phase_id: str
    name: str
    theme_name: str
    theme_type: str
    deadline: date | None
    progress: str  # 如 "3/6"
    remaining_tasks: int


class PendingTaskInfo(BaseModel):
    task_id: str
    name: str
    phase_id: str
    phase_name: str
    phase_deadline: date | None
    theme_type: str


class DailyPoolData(BaseModel):
    date: date
    yesterday_completed: list[YesterdayCompletedTask]
    yesterday_unconfirmed: bool
    active_phases: list[ActivePhaseInfo]
    pending_tasks: list[PendingTaskInfo]
    global_active_count: int
    global_active_limit: int = 3


# ---- POST /daily/confirm 请求/响应 ----


class PreSubtaskInput(BaseModel):
    """前置子任务输入（pm-subtask 生成，与任务解耦，无 task_id）。"""

    name: str
    type: str = "前置"
    description: str | None = None


class DailyConfirmRequest(BaseModel):
    user_id: str
    date: date
    task_ids: list[str] = Field(..., min_length=1)
    pre_subtasks: list[PreSubtaskInput] = Field(default_factory=list)
    push_source: str = "manual"  # auto / manual


class DailyConfirmData(BaseModel):
    daily_id: str
    date: date
    task_count: int
    pre_subtask_count: int
    async_triggered: bool
