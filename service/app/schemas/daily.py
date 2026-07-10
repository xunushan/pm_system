"""今日计划请求/响应模型。详见《服务API文档 v2.0》3.4。

GET  /daily/plans/pool   今日任务池预查询（只读，供 pm-daily LLM 决策）
POST /daily/confirm       确认今日计划（任务勾选+前置勾选 -> INSERT 3 表 + 异步执行）
"""

from datetime import date
from typing import Literal

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
    push_source: Literal["auto", "manual"] = "manual"


class DailyConfirmData(BaseModel):
    daily_id: str
    date: date
    task_count: int
    pre_subtask_count: int
    async_triggered: bool


# ---- GET /daily/summary/generate + POST /daily/summary/confirm (Story5) ----


class DailySummaryTaskItem(BaseModel):
    """日终总结任务项。"""

    task_id: str
    name: str
    theme_name: str


class DailySummaryPhaseHealth(BaseModel):
    """阶段健康度。"""

    phase_id: str
    name: str
    completed: int
    total: int
    rate: float
    status: str


class DailySummaryData(BaseModel):
    """GET /daily/summary/generate 响应（纯查询，无 LLM）。"""

    date: date
    daily_id: str | None = None
    is_confirmed: bool = False
    completed_tasks: list[DailySummaryTaskItem] = []
    incomplete_tasks: list[DailySummaryTaskItem] = []
    phase_health: list[DailySummaryPhaseHealth] = []
    active_phase_count: int = 0
    global_active_limit: int = 3


class DailySummaryConfirmRequest(BaseModel):
    """POST /daily/summary/confirm 请求。"""

    daily_id: str


class DailySummaryConfirmData(BaseModel):
    """POST /daily/summary/confirm 响应。"""

    daily_id: str
    confirmed: bool
    daily_md_path: str | None = None
