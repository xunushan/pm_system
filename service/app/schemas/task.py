"""任务请求/响应模型。详见《服务API文档 v2.0》3.5。

Story4A：
  GET  /tasks/{taskId}                    任务详情
  POST /tasks/{taskId}/confirm-complete   人工确认完成（即时级联，无后置）
  POST /tasks/{taskId}/output/confirm     验收通过智能体产出
  POST /tasks/{taskId}/output/reject      需要修改（重试/通知）
  POST /api/callback/opencode/output      OpenCode 产出回调
  POST /api/callback/opencode/timeout     Redis 超时告警回调

Story4B：
  POST /tasks/{taskId}/complete           标记完成（即时级联，不含后置）
  POST /tasks/{taskId}/post-confirm        后置确认（INSERT 后置，可全取消）
"""

from datetime import datetime

from pydantic import BaseModel, Field


class TaskDetailData(BaseModel):
    """GET /tasks/{taskId} 响应。"""

    task_id: str
    name: str
    description: str | None = None
    status: str
    executor: str | None = None
    phase_id: str
    sort_order: int
    has_subtask: bool
    retry_count: int
    completed_at: datetime | None = None


# ---- POST /tasks/{taskId}/complete (Story4B) ----


class TaskCompleteRequest(BaseModel):
    """POST /tasks/{taskId}/complete 请求。"""

    user_id: str


class CascadeResult(BaseModel):
    """完成级联结果：哪些上级被级联完成。"""

    phase_completed: bool = False
    theme_completed: bool = False
    goal_completed: bool = False


class TaskCompleteData(BaseModel):
    """POST /tasks/{taskId}/complete 响应。"""

    task_id: str
    status: str
    cascade: CascadeResult


# ---- POST /tasks/{taskId}/post-confirm (Story4B) ----


class PostSubtaskInput(BaseModel):
    """后置子任务输入（pm-subtask 生成，用户勾选确认）。"""

    name: str
    type: str = "后置"
    description: str | None = None


class PostConfirmRequest(BaseModel):
    """POST /tasks/{taskId}/post-confirm 请求体（task_id 在 path）。"""

    user_id: str
    post_subtasks: list[PostSubtaskInput] = Field(default_factory=list)


class PostConfirmData(BaseModel):
    """POST /tasks/{taskId}/post-confirm 响应。"""

    task_id: str
    post_subtask_count: int
    async_triggered: bool


class PostConfirmWebhookRequest(BaseModel):
    """story4B_确认后置 / story4B_不需要后置 回调参数（含 task_id，无 path 参数）。"""

    action_id: str
    task_id: str
    user_id: str
    post_subtasks: list[PostSubtaskInput] = Field(default_factory=list)


# ---- POST /tasks/{taskId}/confirm-complete (Story4A) ----


class ConfirmCompleteRequest(BaseModel):
    """POST /tasks/{taskId}/confirm-complete 请求。"""

    user_id: str


class ConfirmCompleteData(BaseModel):
    """POST /tasks/{taskId}/confirm-complete 响应。"""

    task_id: str
    status: str
    cascade: CascadeResult
    opencode_restarted: bool
    next_agent_task: str | None = None


# ---- POST /tasks/{taskId}/output/confirm (Story4A) ----


class OutputConfirmRequest(BaseModel):
    """POST /tasks/{taskId}/output/confirm 请求。"""

    user_id: str
    workspace_progress_ids: list[str] = Field(default_factory=list)


class OutputConfirmData(BaseModel):
    """POST /tasks/{taskId}/output/confirm 响应。"""

    task_id: str
    status: str
    cascade: CascadeResult


# ---- POST /tasks/{taskId}/output/reject (Story4A) ----


class OutputRejectRequest(BaseModel):
    """POST /tasks/{taskId}/output/reject 请求。"""

    user_id: str
    feedback: str


class OutputRejectData(BaseModel):
    """POST /tasks/{taskId}/output/reject 响应。"""

    task_id: str
    retry_count: int
    max_retry: int = 3
    action: str  # "retry" / "manual_intervention"
    async_triggered: bool = False
    opencode_stopped: bool = False
    workspace_path: str | None = None


# ---- POST /api/callback/opencode/output (Story4A) ----


class OpencodeOutputItem(BaseModel):
    """opencode/output 回调中的单个产出项。"""

    file_path: str
    file_type: str  # note/code/resource/exercise/design
    summary: str | None = None


class OpencodeOutputCallbackRequest(BaseModel):
    """POST /api/callback/opencode/output 请求。"""

    task_id: str
    workspace_id: str
    outputs: list[OpencodeOutputItem] = Field(default_factory=list)
    exit_code: int | None = None
    duration: int | None = None


class RecordOutputData(BaseModel):
    """POST /api/callback/opencode/output 响应。"""

    received: bool
    progress_count: int


# ---- POST /api/callback/opencode/timeout (Story4A) ----


class OpencodeTimeoutCallbackRequest(BaseModel):
    """POST /api/callback/opencode/timeout 请求。"""

    task_id: str
    workspace_id: str
    timeout_at: str | None = None
    expected_callback: str | None = None


class TimeoutAlertData(BaseModel):
    """POST /api/callback/opencode/timeout 响应。"""

    alert_sent: bool


# ---- PATCH /tasks/{taskId} (Story5 日终异议双向) ----


class TaskPatchStatusRequest(BaseModel):
    """PATCH /tasks/{taskId} 请求（日终异议双向状态变更）。

    status: 目标状态（已完成=forward / 待执行=revert）。
    triggered_by: 触发者（user/agent_callback/supervisor）。
    completed_at: 完成时间（forward 时可选，默认 now）。

    revert 的 reason 由系统自动填（日终异议-标记未完成），不弹窗（D18 裁决）。
    """

    status: str  # 已完成 / 待执行
    completed_at: datetime | None = None
    triggered_by: str = "user"


class RevertCascadeResult(BaseModel):
    """回退级联结果：哪些上级被级联回退。"""

    phase_reverted: bool = False
    theme_reverted: bool = False
    goal_reverted: bool = False


class TaskPatchStatusData(BaseModel):
    """PATCH /tasks/{taskId} 响应。"""

    task_id: str
    status: str
    cascade: CascadeResult | RevertCascadeResult
