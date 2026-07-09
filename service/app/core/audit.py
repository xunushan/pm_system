"""状态变更审计：写 status_change_log。

change_type: forward / pause / resume / revert / cascade
triggered_by: user / agent_callback / supervisor / cascade
回退/暂停必填 reason。详见《数据模型文档 v2.0》2.11。

Story2 实现：forward（用户触发）+ cascade（级联触发）。S5 扩 pause/resume/revert。
"""

from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.status_change_log import StatusChangeLog


def log_status_change(
    db: Session,
    entity_type: str,
    entity_id: str,
    from_status: str | None,
    to_status: str,
    change_type: str,
    triggered_by: str,
    reason: str | None = None,
) -> None:
    """写一条 status_change_log（add+flush，不 commit；commit 由 AppSvc 管理）。"""
    log = StatusChangeLog(
        id=str(uuid4()),
        entity_type=entity_type,
        entity_id=entity_id,
        from_status=from_status,
        to_status=to_status,
        change_type=change_type,
        reason=reason,
        triggered_by=triggered_by,
    )
    db.add(log)
    db.flush()  # 触发 server_default（changed_at），便于审计回查
