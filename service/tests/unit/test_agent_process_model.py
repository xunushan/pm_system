"""Story4A 单元测试：agent_processes model + UNIQUE(workspace_id) 约束。"""

from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.agent_process import AgentProcess
from app.models.workspace import Workspace
from tests._factory import make_tree


def _make_workspace(db, theme=None):
    """创建一个 workspace 记录。"""
    if theme is None:
        _, themes, _ = make_tree(db, n_themes=1, phases_per_theme=0)
        theme = themes[0]
    ws = Workspace(
        id=str(uuid4()),
        theme_id=theme.id,
        path=f"data/workspaces/{uuid4().hex[:8]}",
        managed=True,
        status="已就绪",
        type=theme.type,
    )
    db.add(ws)
    db.flush()
    return ws


def test_agent_process_create_defaults(db_session):
    """创建 agent_process，默认 status=running。"""
    ws = _make_workspace(db_session)
    ap = AgentProcess(
        id=str(uuid4()),
        workspace_id=ws.id,
        port=10001,
    )
    db_session.add(ap)
    db_session.flush()

    assert ap.status == "running"
    assert ap.started_at is not None
    assert ap.pid is None
    assert ap.last_heartbeat is None
    assert ap.task_queue is None


def test_agent_process_unique_workspace(db_session):
    """UNIQUE(workspace_id)：同一 workspace 不能有两条记录。"""
    ws = _make_workspace(db_session)
    ap1 = AgentProcess(id=str(uuid4()), workspace_id=ws.id, port=10001)
    db_session.add(ap1)
    db_session.flush()

    ap2 = AgentProcess(id=str(uuid4()), workspace_id=ws.id, port=10002)
    db_session.add(ap2)
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_agent_process_status_check_constraint(db_session):
    """status CHECK running/crashed/stopped。"""
    ws = _make_workspace(db_session)
    ap = AgentProcess(id=str(uuid4()), workspace_id=ws.id, port=10001, status="invalid")
    db_session.add(ap)
    with pytest.raises(IntegrityError):
        db_session.flush()
