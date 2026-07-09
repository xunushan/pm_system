"""agent_processes 表 Repository（纯 CRUD + 按状态/workspace 查询）。"""

from sqlalchemy import select

from app.models.agent_process import AgentProcess
from app.repositories.base import BaseRepository


class AgentProcessRepository(BaseRepository[AgentProcess]):
    __model__ = AgentProcess

    def get_by_workspace(self, workspace_id: str) -> AgentProcess | None:
        """按 workspace_id 唯一查询（UNIQUE 约束）。"""
        return self.db.scalar(select(AgentProcess).where(AgentProcess.workspace_id == workspace_id))

    def get_running_by_workspace(self, workspace_id: str) -> AgentProcess | None:
        """查询 workspace 下 running 状态的进程。"""
        return self.db.scalar(
            select(AgentProcess).where(
                AgentProcess.workspace_id == workspace_id,
                AgentProcess.status == "running",
            )
        )

    def list_by_status(self, status: str) -> list[AgentProcess]:
        """按状态查询进程列表。"""
        return list(self.db.scalars(select(AgentProcess).where(AgentProcess.status == status)))

    def get_used_ports(self) -> set[int]:
        """查询所有 running 进程已占用的端口。"""
        rows = self.db.execute(
            select(AgentProcess.port).where(AgentProcess.status == "running")
        ).all()
        return {r[0] for r in rows}
