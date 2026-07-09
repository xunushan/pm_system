"""DraftAppSvc 乐观锁与 CRUD 单元测试（直连 db_session）。"""

from datetime import timedelta

import pytest

from app.core.exceptions import BadRequestError, ConflictError, DraftExpiredError, NotFoundError
from app.models.draft import Draft
from app.services.draft_app_svc import DraftAppSvc, now_utc_naive

_CONTENT = {"goal": {"name": "G"}, "themes": []}


def test_create_and_get(db_session):
    svc = DraftAppSvc(db_session)
    created = svc.create(user_id="u1", story_type="plan", content=_CONTENT)
    assert created.status == "pending"
    assert created.draft_id

    got = svc.get(created.draft_id)
    assert got.version == 1
    assert got.content == _CONTENT
    assert got.user_id == "u1"


def test_update_version_increment(db_session):
    svc = DraftAppSvc(db_session)
    created = svc.create(user_id="u1", story_type="plan", content=_CONTENT)

    updated = svc.update(draft_id=created.draft_id, content={"goal": {"name": "G2"}}, version=1)
    assert updated.version == 2

    got = svc.get(created.draft_id)
    assert got.version == 2
    assert got.content == {"goal": {"name": "G2"}}


def test_update_version_mismatch_raises_conflict(db_session):
    svc = DraftAppSvc(db_session)
    created = svc.create(user_id="u1", story_type="plan", content=_CONTENT)

    with pytest.raises(ConflictError):
        svc.update(draft_id=created.draft_id, content={"goal": {"name": "G2"}}, version=999)


def test_update_stale_version_after_increment_raises_conflict(db_session):
    """version 升到 2 后，再用旧 version=1 更新应 409。"""
    svc = DraftAppSvc(db_session)
    created = svc.create(user_id="u1", story_type="plan", content=_CONTENT)
    svc.update(draft_id=created.draft_id, content={"goal": {"name": "G2"}}, version=1)
    with pytest.raises(ConflictError):
        svc.update(draft_id=created.draft_id, content={"goal": {"name": "G3"}}, version=1)


def test_update_nonexistent_raises_not_found(db_session):
    svc = DraftAppSvc(db_session)
    with pytest.raises(NotFoundError):
        svc.update(draft_id="no-such-id", content=_CONTENT, version=1)


def test_get_nonexistent_raises_not_found(db_session):
    svc = DraftAppSvc(db_session)
    with pytest.raises(NotFoundError):
        svc.get("no-such-id")


def test_delete(db_session):
    svc = DraftAppSvc(db_session)
    created = svc.create(user_id="u1", story_type="plan", content=_CONTENT)
    svc.delete(created.draft_id)
    with pytest.raises(NotFoundError):
        svc.get(created.draft_id)


def test_delete_nonexistent_raises_not_found(db_session):
    svc = DraftAppSvc(db_session)
    with pytest.raises(NotFoundError):
        svc.delete("no-such-id")


def test_create_rejects_bad_story_type(db_session):
    svc = DraftAppSvc(db_session)
    with pytest.raises(BadRequestError):
        svc.create(user_id="u1", story_type="bogus", content=_CONTENT)


def test_content_roundtrip_unicode(db_session):
    """中文 content 序列化/反序列化保持原样。"""
    svc = DraftAppSvc(db_session)
    content = {"goal": {"name": "具身智能算法岗面试准备"}, "themes": []}
    created = svc.create(user_id="u1", story_type="plan", content=content)
    got = svc.get(created.draft_id)
    assert got.content["goal"]["name"] == "具身智能算法岗面试准备"


def test_uuid_is_unique_per_create(db_session):
    svc = DraftAppSvc(db_session)
    c1 = svc.create(user_id="u1", story_type="plan", content=_CONTENT)
    c2 = svc.create(user_id="u1", story_type="plan", content=_CONTENT)
    assert c1.draft_id != c2.draft_id


def test_update_expired_draft_raises_expired(db_session):
    """过期 draft 更新 -> DraftExpiredError (code 1007)。"""
    svc = DraftAppSvc(db_session)
    created = svc.create(user_id="u1", story_type="plan", content=_CONTENT)
    # 置 expires_at 为过去
    draft = db_session.get(Draft, created.draft_id)
    draft.expires_at = now_utc_naive() - timedelta(hours=1)
    db_session.commit()

    with pytest.raises(DraftExpiredError):
        svc.update(draft_id=created.draft_id, content=_CONTENT, version=1)
