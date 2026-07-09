"""tasks model 约束测试：CHECK status / executor 允许 NULL / UNIQUE(phase_id,sort_order)。"""

from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.goal import Goal
from app.models.phase import Phase
from app.models.task import Task
from app.models.theme import Theme


def _make_phase(db_session, name="目标A") -> Phase:
    g = Goal(id=str(uuid4()), name=name, status="未开始")
    db_session.add(g)
    db_session.flush()  # 先落库，供 theme FK 引用
    t = Theme(id=str(uuid4()), goal_id=g.id, name="专题", type="learning", status="未开始")
    db_session.add(t)
    db_session.flush()  # 先落库，供 phase FK 引用
    p = Phase(id=str(uuid4()), theme_id=t.id, sort_order=1, name="阶段", status="未开始")
    db_session.add(p)
    db_session.flush()  # 先落库，供 task FK 引用
    db_session.commit()
    return p


def test_task_insert_with_defaults(db_session):
    p = _make_phase(db_session)
    task = Task(id=str(uuid4()), phase_id=p.id, sort_order=1, name="任务1")
    db_session.add(task)
    db_session.commit()

    got = db_session.query(Task).one()
    assert got.status == "待执行"
    assert got.executor is None  # 规划态不填
    assert got.has_subtask is False
    assert got.retry_count == 0


@pytest.mark.parametrize("bad_status", ["待执行x", "pending", "", "已完成 "])
def test_task_status_check_rejects_invalid(db_session, bad_status):
    p = _make_phase(db_session)
    task = Task(id=str(uuid4()), phase_id=p.id, sort_order=1, name="任务", status=bad_status)
    db_session.add(task)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


@pytest.mark.parametrize("bad_executor", ["", "human2", "AGENT", "bot"])
def test_task_executor_check_rejects_invalid(db_session, bad_executor):
    p = _make_phase(db_session)
    task = Task(id=str(uuid4()), phase_id=p.id, sort_order=1, name="任务", executor=bad_executor)
    db_session.add(task)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


@pytest.mark.parametrize("valid_executor", ["human", "agent"])
def test_task_executor_accepts_valid(db_session, valid_executor):
    p = _make_phase(db_session)
    task = Task(id=str(uuid4()), phase_id=p.id, sort_order=1, name="任务", executor=valid_executor)
    db_session.add(task)
    db_session.commit()
    assert db_session.query(Task).one().executor == valid_executor


def test_task_executor_null_allowed(db_session):
    """executor 规划态为 NULL（CHECK 允许 NULL）。"""
    p = _make_phase(db_session)
    task = Task(id=str(uuid4()), phase_id=p.id, sort_order=1, name="任务", executor=None)
    db_session.add(task)
    db_session.commit()
    assert db_session.query(Task).one().executor is None


def test_task_unique_phase_sort(db_session):
    p = _make_phase(db_session)
    t1 = Task(id=str(uuid4()), phase_id=p.id, sort_order=1, name="任务1")
    db_session.add(t1)
    db_session.commit()
    t2 = Task(id=str(uuid4()), phase_id=p.id, sort_order=1, name="任务重复")
    db_session.add(t2)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_task_phase_id_fk_required(db_session):
    task = Task(id=str(uuid4()), phase_id="not-exist", sort_order=1, name="孤儿任务")
    db_session.add(task)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
