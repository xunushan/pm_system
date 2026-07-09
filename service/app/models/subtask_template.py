"""子任务模板表 ORM。详见《数据模型文档 v2.0》2.6 表7。

用户在 H5 页面配置执行前后的固定工作（前置/后置模板）。
配置粒度：专题或阶段，阶段级优先于专题级，同名去重（doc/02 2.18）。
配置时不校验专题 type（智能体专题配了也不提示，生成时自然跳过）。
删除标记 inactive（非物理删除，可恢复）。走 H5 CRUD，不建 Skill（doc/03 8.13）。
"""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SubtaskTemplate(Base):
    __tablename__ = "subtask_templates"
    __table_args__ = (
        CheckConstraint(
            "scope_type IN ('theme','phase')",
            name="ck_subtask_templates_scope_type",
        ),
        CheckConstraint(
            "type IN ('前置','后置')",
            name="ck_subtask_templates_type",
        ),
        CheckConstraint(
            "status IN ('active','inactive')",
            name="ck_subtask_templates_status",
        ),
        UniqueConstraint("scope_id", "type", "name", name="uq_subtask_templates_scope_type_name"),
        # 业务索引（doc/02 2.13）：按 scope 查询 + 按 name 唯一性检查
        Index("idx_subtask_templates_scope", "scope_type", "scope_id", "type", "status"),
        Index("idx_subtask_templates_name", "scope_id", "type", "name"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    scope_type: Mapped[str] = mapped_column(String(16), nullable=False)
    scope_id: Mapped[str] = mapped_column(String(36), nullable=False)
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())
