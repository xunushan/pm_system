"""状态变更审计表 ORM。详见《数据模型文档 v2.0》2.11。

记录所有状态流转（forward/pause/resume/revert/cascade），回退/暂停必填 reason。
Story2 起建：实现 forward（用户触发）与 cascade（级联触发）；
S5 扩 pause/resume/revert（含 reason 必填校验）。
"""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class StatusChangeLog(Base):
    __tablename__ = "status_change_log"
    __table_args__ = (
        CheckConstraint(
            "entity_type IN ('goal','theme','phase','task')",
            name="ck_status_log_entity_type",
        ),
        CheckConstraint(
            "change_type IN ('forward','pause','resume','revert','cascade')",
            name="ck_status_log_change_type",
        ),
        CheckConstraint(
            "triggered_by IN ('user','agent_callback','supervisor','cascade')",
            name="ck_status_log_triggered_by",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(16), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(16))
    to_status: Mapped[str] = mapped_column(String(16), nullable=False)
    change_type: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    triggered_by: Mapped[str] = mapped_column(String(16))
    changed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())
