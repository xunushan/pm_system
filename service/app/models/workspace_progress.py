"""工作空间进展表 ORM。详见《数据模型文档 v2.0》2.7 表8。

记录 OpenCode 智能体每次产出文件（产出统一为文件，doc/01 4A）。
opencode/output 回调时写入；验收通过/需要修改时引用 workspace_progress_ids。
"""

from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class WorkspaceProgress(Base):
    __tablename__ = "workspace_progress"
    __table_args__ = (
        CheckConstraint(
            "file_type IN ('note','code','resource','exercise','design')",
            name="ck_workspace_progress_file_type",
        ),
        Index("idx_workspace_progress_ws", "workspace_id", "date"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspaces.id"), nullable=False
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    # nullable：工作空间级产出（非任务关联）时为 NULL
    task_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("tasks.id"))
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_type: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())
