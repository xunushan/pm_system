"""每周记录表 ORM。详见《数据模型文档 v2.0》2.8 表11。

week 唯一（一周一条 weekly_record）。date_range_start/end 为该 ISO 周的周一/周日。
is_confirmed 是"已阅"归档标记（S6 周总结确认时置 true），不触发级联（纯回顾，
doc/01 Story6 设计要点：不修改任何状态）。summary 为 pm-summary LLM 生成的文案快照（可选）。
"""

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class WeeklyRecord(Base):
    __tablename__ = "weekly_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    # ISO 周字符串，如 "2026-W27"
    week: Mapped[str] = mapped_column(String(16), nullable=False, unique=True)
    date_range_start: Mapped[date] = mapped_column(Date, nullable=False)
    date_range_end: Mapped[date] = mapped_column(Date, nullable=False)
    # "已阅"归档标记（不触发级联）；confirm 时置 true
    is_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime)
    # pm-summary LLM 生成的周总结文案快照（可选，由调用方写入）
    summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())
