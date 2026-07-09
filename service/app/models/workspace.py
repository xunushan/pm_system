"""工作空间表 ORM。详见《数据模型文档 v2.0》2.4。

与专题 1:1（theme_id UNIQUE）。managed 决定初始化分支：
  - managed=1（默认，系统托管）：激活时异步初始化（mkdir+git init+骨架含规范文件）。
  - managed=0（关联已有）：激活时仅校验 path 存在性，不创建任何文件，直接置已就绪。
managed/path 在 Story2 卡片 A 设置；激活后不能改 managed（避免破坏已初始化目录）。
"""

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Workspace(Base):
    __tablename__ = "workspaces"
    __table_args__ = (
        CheckConstraint(
            "status IN ('未初始化','已就绪','运行中','空闲')",
            name="ck_workspaces_status",
        ),
        CheckConstraint(
            "type IN ('learning','research','source','dev','survey')",
            name="ck_workspaces_type",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    # 与专题 1:1（UNIQUE）；激活阶段时创建，type 继承自 theme.type
    theme_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("themes.id"), nullable=False, unique=True
    )
    # managed=1 时系统生成；managed=0 时用户指定
    path: Mapped[str] = mapped_column(Text, nullable=False)
    managed: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(16), default="未初始化")
    type: Mapped[str] = mapped_column(String(16), default="learning")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())
    # 主 Agent 进程心跳（Story4A 起）；激活初始化阶段为 NULL
    last_heartbeat: Mapped[datetime | None] = mapped_column(DateTime)
