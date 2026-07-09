"""themes model 约束测试：CHECK 拒绝非法 type/status。"""

from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.goal import Goal
from app.models.theme import Theme


def _make_goal(db_session, name="目标A") -> Goal:
    g = Goal(id=str(uuid4()), name=name, status="未开始")
    db_session.add(g)
    db_session.flush()  # 先落库，供 theme FK 引用
    db_session.commit()
    return g


def test_theme_insert_with_defaults(db_session):
    g = _make_goal(db_session)
    t = Theme(id=str(uuid4()), goal_id=g.id, name="专题1")
    db_session.add(t)
    db_session.commit()

    got = db_session.query(Theme).one()
    assert got.type == "learning"  # default
    assert got.status == "未开始"  # default
    assert got.created_at is not None


@pytest.mark.parametrize("bad_type", ["", "learning2", "LEARNING", "other", "devv"])
def test_theme_type_check_rejects_invalid(db_session, bad_type):
    g = _make_goal(db_session)
    t = Theme(id=str(uuid4()), goal_id=g.id, name="专题", type=bad_type)
    db_session.add(t)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


@pytest.mark.parametrize("valid_type", ["learning", "research", "source", "dev", "survey"])
def test_theme_type_accepts_valid(db_session, valid_type):
    g = _make_goal(db_session)
    t = Theme(id=str(uuid4()), goal_id=g.id, name=f"专题{valid_type}", type=valid_type)
    db_session.add(t)
    db_session.commit()
    assert db_session.query(Theme).one().type == valid_type


def test_theme_status_check_rejects_invalid(db_session):
    g = _make_goal(db_session)
    t = Theme(id=str(uuid4()), goal_id=g.id, name="专题", status="进行中x")
    db_session.add(t)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_theme_goal_id_fk_required(db_session):
    """goal_id NOT NULL + FK -> 缺失应报错。"""
    t = Theme(id=str(uuid4()), goal_id="not-exist", name="孤儿专题")
    db_session.add(t)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
