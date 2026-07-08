"""目标表 ORM。详见《数据模型文档 v2.0》2.2 表1。

此文件为 model 实现的【范本】：其余 model 按本文件的模式编写
（TEXT 主键 UUID、Mapped 类型、CheckConstraint 约束、server_default 时间戳）。
"""

from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Goal(Base):
    __tablename__ = "goals"
    __table_args__ = (
        CheckConstraint(
            "status IN ('未开始','进行中','已完成','已暂停')",
            name="ck_goals_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    # 目标时间范围（粗略，规划态确认）
    time_range_start: Mapped[date | None] = mapped_column(Date)
    time_range_end: Mapped[date | None] = mapped_column(Date)
    # 计划开始日（规划态确认，用于提醒激活；每日计划不用此过滤）
    scheduled_start_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), default="未开始")
    status_changed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())
