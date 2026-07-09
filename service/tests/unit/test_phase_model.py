"""phases model 约束测试：CHECK status / UNIQUE(theme_id,sort_order) / FK。"""

from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.goal import Goal
from app.models.phase import Phase
from app.models.theme import Theme


def _make_theme(db_session, name="目标A") -> Theme:
    g = Goal(id=str(uuid4()), name=name, status="未开始")
    db_session.add(g)
    db_session.flush()  # 先落库，供 theme FK 引用
    t = Theme(id=str(uuid4()), goal_id=g.id, name="专题", type="learning", status="未开始")
    db_session.add(t)
    db_session.flush()  # 先落库，供 phase FK 引用
    db_session.commit()
    return t


def test_phase_insert_with_defaults(db_session):
    t = _make_theme(db_session)
    p = Phase(id=str(uuid4()), theme_id=t.id, sort_order=1, name="阶段1")
    db_session.add(p)
    db_session.commit()

    got = db_session.query(Phase).one()
    assert got.status == "未开始"
    assert got.deadline is None  # 规划态
    assert got.activated_at is None


@pytest.mark.parametrize("bad_status", ["未开始x", "completed", "", "进行中 "])
def test_phase_status_check_rejects_invalid(db_session, bad_status):
    t = _make_theme(db_session)
    p = Phase(id=str(uuid4()), theme_id=t.id, sort_order=1, name="阶段", status=bad_status)
    db_session.add(p)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_phase_unique_theme_sort(db_session):
    """UNIQUE(theme_id, sort_order) -> 同专题同序号冲突。"""
    t = _make_theme(db_session)
    p1 = Phase(id=str(uuid4()), theme_id=t.id, sort_order=1, name="阶段1")
    db_session.add(p1)
    db_session.commit()
    p2 = Phase(id=str(uuid4()), theme_id=t.id, sort_order=1, name="阶段1重复")
    db_session.add(p2)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_phase_same_sort_different_theme_ok(db_session):
    """不同专题同序号不冲突。"""
    t1 = _make_theme(db_session, name="目标A")
    g2 = Goal(id=str(uuid4()), name="目标B", status="未开始")
    db_session.add(g2)
    t2 = Theme(id=str(uuid4()), goal_id=g2.id, name="专题B", type="dev", status="未开始")
    db_session.add(t2)
    db_session.commit()

    p1 = Phase(id=str(uuid4()), theme_id=t1.id, sort_order=1, name="阶段A1")
    p2 = Phase(id=str(uuid4()), theme_id=t2.id, sort_order=1, name="阶段B1")
    db_session.add_all([p1, p2])
    db_session.commit()
    assert db_session.query(Phase).count() == 2


def test_phase_theme_id_fk_required(db_session):
    p = Phase(id=str(uuid4()), theme_id="not-exist", sort_order=1, name="孤儿阶段")
    db_session.add(p)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
