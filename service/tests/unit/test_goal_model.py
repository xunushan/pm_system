"""goal model 冒烟测试：验证 ORM 范本（Mapped 类型 + CHECK 约束）可用。"""

from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.goal import Goal


def test_goal_insert_and_query(db_session):
    g = Goal(id=str(uuid4()), name="学完系统设计", status="未开始")
    db_session.add(g)
    db_session.commit()

    assert db_session.query(Goal).count() == 1
    assert db_session.query(Goal).one().status == "未开始"


def test_goal_status_check_constraint_rejects_invalid(db_session):
    """非法 status 应被 CHECK 约束拒绝（SQLite 层强制）。"""
    g = Goal(id=str(uuid4()), name="非法状态测试", status="非法状态")
    db_session.add(g)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
