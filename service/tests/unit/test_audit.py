"""audit 单元测试：写 status_change_log。详见 doc/02 2.11。"""

from app.core import audit
from app.models.status_change_log import StatusChangeLog


def test_log_status_change_writes_forward_record(db_session):
    audit.log_status_change(
        db_session,
        entity_type="phase",
        entity_id="phase-1",
        from_status="未开始",
        to_status="进行中",
        change_type="forward",
        triggered_by="user",
    )
    db_session.commit()
    logs = db_session.query(StatusChangeLog).all()
    assert len(logs) == 1
    log = logs[0]
    assert log.entity_type == "phase"
    assert log.entity_id == "phase-1"
    assert log.from_status == "未开始"
    assert log.to_status == "进行中"
    assert log.change_type == "forward"
    assert log.triggered_by == "user"
    assert log.reason is None
    assert log.changed_at is not None


def test_log_status_change_forward_and_cascade_two_records(db_session):
    """forward（用户触发）+ cascade（级联触发）各写一条。"""
    audit.log_status_change(
        db_session,
        entity_type="phase",
        entity_id="phase-1",
        from_status="未开始",
        to_status="进行中",
        change_type="forward",
        triggered_by="user",
    )
    audit.log_status_change(
        db_session,
        entity_type="theme",
        entity_id="theme-1",
        from_status="未开始",
        to_status="进行中",
        change_type="cascade",
        triggered_by="cascade",
    )
    db_session.commit()
    logs = db_session.query(StatusChangeLog).order_by(StatusChangeLog.changed_at).all()
    assert len(logs) == 2
    assert logs[0].change_type == "forward"
    assert logs[1].change_type == "cascade"
    assert logs[1].triggered_by == "cascade"
