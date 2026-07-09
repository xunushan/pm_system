"""项目空间主 Agent 进程表 ORM。详见《数据模型文档 v2.0》2.10 表13。

记录 opencode serve 进程：workspace_id UNIQUE（一个工作空间一个常驻 serve）。
端口动态分配（10000-20000，见《系统架构文档》五）。
启动时机：首次下发智能体任务时（Story3 确认后），非 Story2 激活时。
生命周期：阶段级常驻；阶段完成/3次重试不通过退出；"/pm 确认完成"后重启不同端口。
"""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AgentProcess(Base):
    __tablename__ = "agent_processes"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running','crashed','stopped')",
            name="ck_agent_processes_status",
        ),
        Index("idx_agent_processes_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    # UNIQUE：一个 workspace 一个常驻 serve
    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspaces.id"), nullable=False, unique=True
    )
    port: Mapped[int] = mapped_column(Integer, nullable=False)
    pid: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="running")
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())
    last_heartbeat: Mapped[datetime | None] = mapped_column(DateTime)
    # 待执行任务队列（JSON 字符串）
    task_queue: Mapped[str | None] = mapped_column(Text)
