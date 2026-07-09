"""专题表 ORM。详见《数据模型文档 v2.0》2.2 表2。

专题无序（无 sort_order / time_range），并列可跨专题并行推进。
type 用于 pm-daily 推断 executor（learning/research/source->human；dev/survey->agent）。
"""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Theme(Base):
    __tablename__ = "themes"
    __table_args__ = (
        CheckConstraint(
            "type IN ('learning','research','source','dev','survey')",
            name="ck_themes_type",
        ),
        CheckConstraint(
            "status IN ('未开始','进行中','已完成','已暂停')",
            name="ck_themes_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    goal_id: Mapped[str] = mapped_column(String(36), ForeignKey("goals.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    # 用于推断 executor；规划态确认时填入
    type: Mapped[str] = mapped_column(String(16), default="learning")
    status: Mapped[str] = mapped_column(String(16), default="未开始")
    status_changed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())
