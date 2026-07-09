"""子任务请求/响应模型。详见《服务API文档 v2.0》3.9。

POST   /subtasks             创建子任务（前置/后置，由 pm-subtask 生成后调用）
GET    /subtasks/{subtaskId}  获取子任务详情
PATCH  /subtasks/{subtaskId}  更新子任务状态（异步执行完成后回调）
"""

from datetime import datetime

from pydantic import BaseModel


class SubtaskCreateRequest(BaseModel):
    task_id: str
    name: str
    type: str  # 前置 / 后置
    description: str | None = None


class SubtaskPatchRequest(BaseModel):
    status: str | None = None
    output_path: str | None = None


class SubtaskData(BaseModel):
    subtask_id: str
    task_id: str
    name: str
    description: str | None
    type: str
    status: str
    sort_order: int
    output_path: str | None
    completed_at: datetime | None
