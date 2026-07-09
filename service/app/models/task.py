"""任务表 ORM。详见《数据模型文档 v2.0》2.3 表4。

任务排序不强制（sort_order 仅记录，pm-daily 动态定今日顺序）。
executor 规划态不填（NULL），pm-daily 按所属专题 type 推断填入
（learning/research/source->human；dev/survey->agent）。
has_subtask 在生成前置/后置时置 true（Story3+）。
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint(
            "status IN ('待执行','已完成','已暂停')",
            name="ck_tasks_status",
        ),
        # executor 规划态不填（NULL）；推断后为 human/agent
        CheckConstraint(
            "executor IS NULL OR executor IN ('human','agent')",
            name="ck_tasks_executor",
        ),
        UniqueConstraint("phase_id", "sort_order", name="uq_tasks_phase_sort"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    phase_id: Mapped[str] = mapped_column(String(36), ForeignKey("phases.id"), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="待执行")
    status_changed_at: Mapped[datetime | None] = mapped_column(DateTime)
    # 规划态不填（NULL），pm-daily 按专题 type 推断
    executor: Mapped[str | None] = mapped_column(String(16))
    has_subtask: Mapped[bool] = mapped_column(Boolean, default=False)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    paused_at: Mapped[datetime | None] = mapped_column(DateTime)
