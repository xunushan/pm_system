"""子任务模板请求/响应模型。详见《服务API文档 v2.0》3.10。

GET    /subtask-templates           查询模板列表（含合并查询）
POST   /subtask-templates            创建模板
PUT    /subtask-templates/{id}        更新模板
DELETE /subtask-templates/{id}        删除模板（标记 inactive）
"""

from datetime import datetime

from pydantic import BaseModel


class SubtaskTemplateCreateRequest(BaseModel):
    scope_type: str  # theme / phase
    scope_id: str
    type: str  # 前置 / 后置
    name: str
    description: str | None = None


class SubtaskTemplateUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    status: str | None = None  # active / inactive


class SubtaskTemplateData(BaseModel):
    id: str
    scope_type: str
    scope_id: str
    type: str
    name: str
    description: str | None
    status: str
    created_at: datetime
    updated_at: datetime


class SubtaskTemplateListData(BaseModel):
    templates: list[SubtaskTemplateData]


class SubtaskTemplateDeleteData(BaseModel):
    id: str
    status: str
