"""草稿表 ORM。详见《数据模型文档 v2.0》2.9。

drafts 纯存储（不同步展示，不进 H5/多维表格），用于确认前数据传递：
pm-plan 生成规划时写入 drafts（content 存完整规划 JSON，可达几十 KB），
确认按钮回调只传 draft_id（规避飞书回调约 30KB 限制）。
Service 收到回调用 draft_id 读 drafts -> 写正式表 -> 删 drafts。
version 乐观锁防止并发覆盖；expires_at 24h 过期。
"""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Draft(Base):
    __tablename__ = "drafts"
    __table_args__ = (
        CheckConstraint(
            "story_type IN ('plan','schedule','daily','weekly','edit','config')",
            name="ck_drafts_story_type",
        ),
        CheckConstraint(
            "status IN ('pending','confirmed','expired','discarded')",
            name="ck_drafts_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    story_type: Mapped[str] = mapped_column(String(16), nullable=False)
    # 关联实体 id（plan 态为 NULL，确认后回填 goal_id；edit/config 态用）
    entity_id: Mapped[str | None] = mapped_column(String(36))
    # 完整规划 JSON（含 goal+themes+phases+tasks），可达几十 KB
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)
