"""子任务表 ORM。详见《数据模型文档 v2.0》2.5 表6。

前置/后置只服务人执行任务，智能体执行（opencode run）。
前置按"今日整体"生成（不按单个任务，与任务解耦）；后置按单个任务生成。
Story3 起建表 + 前置 INSERT（confirm 时）；S4B 扩后置 + 完成。

task_id NOT NULL（doc/02 §2.5）。前置"今日整体"语义下 task_id 为 FK 锚点
（关联到今日勾选的第一个 theme_type=human 的任务），非语义绑定。
详见 PR 说明（张力1）。
"""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Subtask(Base):
    __tablename__ = "subtasks"
    __table_args__ = (
        CheckConstraint(
            "type IN ('前置','后置')",
            name="ck_subtasks_type",
        ),
        CheckConstraint(
            "status IN ('待执行','进行中','已完成','失败')",
            name="ck_subtasks_status",
        ),
        UniqueConstraint("task_id", "sort_order", name="uq_subtasks_task_sort"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    # NOT NULL（doc/02 §2.5）。前置"今日整体"时为 FK 锚点（见类 docstring）。
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("tasks.id"), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="待执行")
    output_path: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
