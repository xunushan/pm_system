"""任务请求/响应模型。详见《服务API文档 v2.0》3.5。

GET  /tasks/{taskId}              获取任务详情
POST /tasks/{taskId}/complete      Story4B 标记完成（即时级联，不含后置）
POST /tasks/{taskId}/post-confirm  Story4B 后置确认（INSERT 后置，可全取消）

confirm-complete / output 端点属 Story4A，本文件不实现。
"""

from datetime import datetime

from pydantic import BaseModel, Field

# ---- POST /tasks/{taskId}/complete ----


class TaskCompleteRequest(BaseModel):
    user_id: str


class CascadeResult(BaseModel):
    """完成级联结果：哪些上级被级联完成。"""

    phase_completed: bool = False
    theme_completed: bool = False
    goal_completed: bool = False


class TaskCompleteData(BaseModel):
    task_id: str
    status: str
    cascade: CascadeResult


# ---- POST /tasks/{taskId}/post-confirm ----


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
    task_id: str
    post_subtask_count: int
    async_triggered: bool


# ---- GET /tasks/{taskId} ----


class TaskDetail(BaseModel):
    task_id: str
    name: str
    description: str | None
    status: str
    executor: str | None
    phase_id: str
    sort_order: int
    has_subtask: bool
    completed_at: datetime | None


# ---- 飞书卡片 webhook 请求（含 task_id，无 path 参数）----


class PostConfirmWebhookRequest(BaseModel):
    """story4B_确认后置 / story4B_不需要后置 回调参数。"""

    action_id: str
    task_id: str
    user_id: str
    post_subtasks: list[PostSubtaskInput] = Field(default_factory=list)
