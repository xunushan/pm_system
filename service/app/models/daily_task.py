"""每日任务关联表 ORM。详见《数据模型文档 v2.0》2.8 表10。

daily_tasks 是 daily_records -> tasks 的多对多关联（含 notes）。
UNIQUE(daily_id, task_id) 防止同一日重复勾选同一任务。
注：doc/02 §2.8 表无 created_at 列，以 doc 为准。
"""

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DailyTask(Base):
    __tablename__ = "daily_tasks"
    __table_args__ = (UniqueConstraint("daily_id", "task_id", name="uq_daily_tasks_daily_task"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    daily_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("daily_records.id"), nullable=False
    )
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("tasks.id"), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
