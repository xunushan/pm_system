"""WorkspaceAppSvc：工作空间初始化（managed=1）与关联（managed=0）。

managed=1（托管）：异步初始化（mkdir+git init+骨架含规范文件），事务后由 BackgroundTasks 调用，
  独立 session（请求 session 已关闭）。完成后置 status='已就绪'。
managed=0（关联）：校验 path 存在性（不存在 -> 1002），不创建任何文件，置 status='已就绪'。

铁律 §3#3：初始化（IO）在事务外异步；link 的 path 校验是快速 stat，可同步。
"""

import logging

from sqlalchemy.orm import Session

from app.clients.workspace import init_workspace_dir, is_path_valid
from app.core.exceptions import BadRequestError, ConflictError, NotFoundError
from app.db.session import SessionLocal
from app.models.workspace import Workspace
from app.repositories.workspace import WorkspaceRepository
from app.schemas.workspace import WorkspaceData

logger = logging.getLogger(__name__)


class WorkspaceAppSvc:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = WorkspaceRepository(db)

    def link(self, workspace_id: str, path: str) -> WorkspaceData:
        """managed=0 关联已有路径：校验 path 存在（不存在 1002），不创建文件，置已就绪。

        托管（managed=1）工作空间不能关联 -> 409（激活后不能改 managed）。
        """
        ws = self.repo.get(workspace_id)
        if ws is None:
            raise NotFoundError(f"工作空间不存在: {workspace_id}")
        if ws.managed:
            raise ConflictError("托管工作空间不能关联路径（managed 不可改）")
        if not is_path_valid(path):
            raise BadRequestError(f"path 不存在: {path}")
        ws.path = path
        ws.status = "已就绪"
        self.db.commit()
        return self._to_data(ws)

    @staticmethod
    def init(workspace_id: str) -> None:
        """managed=1 异步初始化（独立 session，BackgroundTasks 调用）。

        mkdir+git init+骨架 -> 置 status='已就绪'。失败记日志不抛（不影响已提交事务）。
        幂等：非 managed 或非 '未初始化' 状态直接跳过。
        """
        db = SessionLocal()
        try:
            ws = db.get(Workspace, workspace_id)
            if ws is None or not ws.managed or ws.status != "未初始化":
                return
            init_workspace_dir(ws.path)
            ws.status = "已就绪"
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("工作空间初始化失败: %s", workspace_id)
        finally:
            db.close()

    @staticmethod
    def _to_data(ws: Workspace) -> WorkspaceData:
        return WorkspaceData(
            workspace_id=ws.id,
            theme_id=ws.theme_id,
            path=ws.path,
            managed=ws.managed,
            status=ws.status,
            type=ws.type,
            created_at=ws.created_at,
            last_heartbeat=ws.last_heartbeat,
        )
