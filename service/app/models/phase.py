"""阶段表 ORM。详见《数据模型文档 v2.0》2.2 表3。

阶段强约束：保留 sort_order，按 roadmap 顺序激活，激活时自动锁定第1个未开始阶段。
deadline/activated_at 在激活时填（Story2 卡片 B），规划态均为 NULL。
UNIQUE(theme_id, sort_order) 防止同专题内阶段序号重复。
"""

from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Phase(Base):
    __tablename__ = "phases"
    __table_args__ = (
        CheckConstraint(
            "status IN ('未开始','进行中','已完成','已暂停')",
            name="ck_phases_status",
        ),
        UniqueConstraint("theme_id", "sort_order", name="uq_phases_theme_sort"),
        Index("idx_phases_theme", "theme_id", "sort_order"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    theme_id: Mapped[str] = mapped_column(String(36), ForeignKey("themes.id"), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="未开始")
    status_changed_at: Mapped[datetime | None] = mapped_column(DateTime)
    # 激活时填（Story2 卡片 B），规划态 NULL
    deadline: Mapped[date | None] = mapped_column(Date)
    # 激活时间（每日计划以此过滤，不用 goals.scheduled_start_date）
    activated_at: Mapped[date | None] = mapped_column(Date)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    paused_at: Mapped[datetime | None] = mapped_column(DateTime)
