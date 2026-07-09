"""项目空间接口（Story2/9）。详见《服务API文档 v2.0》项目空间节。

managed=1 系统托管（激活初始化 mkdir+git init+骨架含规范文件）；
managed=0 关联已有路径（跳过初始化，不创建任何文件）。激活后不能改 managed。
  POST   /workspaces           触发 managed=1 初始化（异步）
  PUT    /workspaces/{id}/link managed=0 关联已有路径（校验 path，不创建文件）
  GET    /workspaces/{id}      获取详情（Story9，TODO）
"""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, status
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError
from app.db.session import get_db
from app.repositories.workspace import WorkspaceRepository
from app.schemas.common import ApiResponse
from app.schemas.workspace import (
    WorkspaceData,
    WorkspaceInitRequest,
    WorkspaceLinkRequest,
)
from app.services.workspace_app_svc import WorkspaceAppSvc

router = APIRouter()

DBSession = Annotated[Session, Depends(get_db)]


@router.post("", response_model=ApiResponse[WorkspaceData], status_code=status.HTTP_202_ACCEPTED)
def init_workspace(
    payload: WorkspaceInitRequest, db: DBSession, background_tasks: BackgroundTasks
) -> ApiResponse[WorkspaceData]:
    """触发 managed=1 工作空间异步初始化。

    校验 workspace 存在 + managed + 未初始化；202 返回当前状态，初始化后台执行。
    """
    repo = WorkspaceRepository(db)
    ws = repo.get(payload.workspace_id)
    if ws is None:
        raise NotFoundError(f"工作空间不存在: {payload.workspace_id}")
    if not ws.managed:
        raise ConflictError("非托管工作空间请用 link 关联路径")
    if ws.status == "未初始化":
        background_tasks.add_task(WorkspaceAppSvc.init, ws.id)
    data = WorkspaceAppSvc._to_data(ws)
    return ApiResponse(data=data)


@router.put("/{workspace_id}/link", response_model=ApiResponse[WorkspaceData])
def link_workspace(
    workspace_id: str, payload: WorkspaceLinkRequest, db: DBSession
) -> ApiResponse[WorkspaceData]:
    """managed=0 关联已有路径（校验 path 存在 1002，不创建文件，置已就绪）。"""
    data = WorkspaceAppSvc(db).link(workspace_id, payload.path)
    return ApiResponse(data=data)


@router.get("/{workspace_id}", response_model=ApiResponse[WorkspaceData])
def get_workspace(workspace_id: str, db: DBSession) -> ApiResponse[WorkspaceData]:
    """获取工作空间详情（H5 只读查看 managed/path）。Story9 扩展更多字段。"""
    ws = WorkspaceRepository(db).get(workspace_id)
    if ws is None:
        raise NotFoundError(f"工作空间不存在: {workspace_id}")
    return ApiResponse(data=WorkspaceAppSvc._to_data(ws))
