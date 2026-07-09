"""每日记录表 ORM。详见《数据模型文档 v2.0》2.8 表9。

date 唯一（一天一条 daily_record）。week 为 ISO 周字符串（如 "2026-W27"）。
push_source 区分 auto（定时 8:30）/ manual（用户主动触发）。
is_confirmed 是回顾确认标记（S5 日终总结确认时置 true），不触发级联（doc/02 变更5）。
"""

from datetime import date, datetime

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DailyRecord(Base):
    __tablename__ = "daily_records"
    __table_args__ = (
        CheckConstraint(
            "push_source IN ('auto','manual')",
            name="ck_daily_records_push_source",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    date: Mapped[date] = mapped_column(Date, nullable=False, unique=True)
    # ISO 周字符串，如 "2026-W27"
    week: Mapped[str] = mapped_column(String(16), nullable=False)
    push_source: Mapped[str] = mapped_column(String(16), default="manual")
    # 回顾确认标记（不触发级联）；confirm 时置 true
    is_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime)
    summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())
