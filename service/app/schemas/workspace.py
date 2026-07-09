"""工作空间请求/响应模型。详见《服务API文档 v2.0》项目空间节。"""

from datetime import datetime

from pydantic import BaseModel


class WorkspaceInitRequest(BaseModel):
    """managed=1 初始化（事务后异步重试/手动触发）。"""

    workspace_id: str


class WorkspaceLinkRequest(BaseModel):
    """managed=0 关联已有路径（校验 path，不创建文件）。"""

    path: str


class WorkspaceData(BaseModel):
    workspace_id: str
    theme_id: str
    path: str
    managed: bool
    status: str
    type: str
    created_at: datetime
    last_heartbeat: datetime | None = None
