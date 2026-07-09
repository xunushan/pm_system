"""drafts model 约束测试：CHECK story_type/status + version 默认。"""

from datetime import datetime
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.draft import Draft


def test_draft_insert_with_defaults(db_session):
    d = Draft(
        id=str(uuid4()),
        user_id="u1",
        story_type="plan",
        content="{}",
    )
    db_session.add(d)
    db_session.commit()

    got = db_session.query(Draft).one()
    assert got.status == "pending"
    assert got.version == 1
    assert got.created_at is not None
    assert got.expires_at is None
    assert got.entity_id is None


@pytest.mark.parametrize("bad_type", ["", "Plan", "planx", "other"])
def test_draft_story_type_check_rejects_invalid(db_session, bad_type):
    d = Draft(id=str(uuid4()), user_id="u1", story_type=bad_type, content="{}")
    db_session.add(d)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


@pytest.mark.parametrize("valid_type", ["plan", "schedule", "daily", "weekly", "edit", "config"])
def test_draft_story_type_accepts_valid(db_session, valid_type):
    d = Draft(id=str(uuid4()), user_id="u1", story_type=valid_type, content="{}")
    db_session.add(d)
    db_session.commit()
    assert db_session.query(Draft).one().story_type == valid_type


@pytest.mark.parametrize("bad_status", ["", "pending2", "PENDING", "done"])
def test_draft_status_check_rejects_invalid(db_session, bad_status):
    d = Draft(id=str(uuid4()), user_id="u1", story_type="plan", content="{}", status=bad_status)
    db_session.add(d)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_draft_content_not_null(db_session):
    d = Draft(id=str(uuid4()), user_id="u1", story_type="plan", content=None)  # type: ignore[arg-type]
    db_session.add(d)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_draft_user_id_not_null(db_session):
    d = Draft(id=str(uuid4()), user_id=None, story_type="plan", content="{}")  # type: ignore[arg-type]
    db_session.add(d)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_draft_with_expires_at(db_session):
    exp = datetime(2026, 7, 9, 12, 0, 0)
    d = Draft(id=str(uuid4()), user_id="u1", story_type="plan", content="{}", expires_at=exp)
    db_session.add(d)
    db_session.commit()
    got = db_session.query(Draft).one()
    assert got.expires_at == exp
