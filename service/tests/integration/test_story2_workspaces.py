"""Story2 集成测试：workspaces POST(init)/PUT(link)/GET。"""

from uuid import uuid4

from sqlalchemy.orm import sessionmaker

from app.models.workspace import Workspace
from app.services import workspace_app_svc
from tests._factory import make_tree

_API = "/api/v1"


def _make_workspace(db, theme, *, managed=True, status="未初始化", path=None):
    ws = Workspace(
        id=str(uuid4()),
        theme_id=theme.id,
        path=path or f"data/workspaces/{uuid4().hex[:8]}",
        managed=managed,
        status=status,
        type=theme.type,
    )
    db.add(ws)
    db.flush()
    return ws


def test_workspaces_post_init_managed1(client, db_session, monkeypatch):
    """POST /workspaces -> 202，异步 init -> workspace 置已就绪。"""
    goal, themes, _ = make_tree(db_session)
    ws = _make_workspace(db_session, themes[0], managed=True, status="未初始化")
    db_session.flush()

    monkeypatch.setattr(
        workspace_app_svc,
        "SessionLocal",
        sessionmaker(bind=db_session.bind, expire_on_commit=False),
    )
    monkeypatch.setattr(workspace_app_svc, "init_workspace_dir", lambda path: None)

    resp = client.post(f"{_API}/workspaces", json={"workspace_id": ws.id})
    assert resp.status_code == 202, resp.text
    db_session.expire_all()
    assert db_session.get(Workspace, ws.id).status == "已就绪"


def test_workspaces_post_init_managed0_returns_409(client, db_session):
    """非托管工作空间不能 init -> 409。"""
    goal, themes, _ = make_tree(db_session)
    ws = _make_workspace(db_session, themes[0], managed=False, status="已就绪")
    db_session.flush()

    resp = client.post(f"{_API}/workspaces", json={"workspace_id": ws.id})
    assert resp.status_code == 409
    assert resp.json()["code"] == 1003


def test_workspaces_put_link_managed0(client, db_session, tmp_path):
    """PUT /link managed=0 -> 校验 path 存在 -> 置已就绪。"""
    goal, themes, _ = make_tree(db_session)
    ws = _make_workspace(db_session, themes[0], managed=False, status="未初始化")
    db_session.flush()
    existing = tmp_path / "linked"
    existing.mkdir()

    resp = client.put(f"{_API}/workspaces/{ws.id}/link", json={"path": str(existing)})
    assert resp.status_code == 200, resp.text
    db_session.expire_all()
    refreshed = db_session.get(Workspace, ws.id)
    assert refreshed.status == "已就绪"
    assert refreshed.path == str(existing)


def test_workspaces_put_link_managed1_returns_409(client, db_session):
    """托管工作空间不能 link -> 409（managed 不可改）。"""
    goal, themes, _ = make_tree(db_session)
    ws = _make_workspace(db_session, themes[0], managed=True, status="未初始化")
    db_session.flush()

    resp = client.put(f"{_API}/workspaces/{ws.id}/link", json={"path": "/tmp"})
    assert resp.status_code == 409
    assert resp.json()["code"] == 1003


def test_workspaces_put_link_path_not_exists_returns_1002(client, db_session):
    """link path 不存在 -> 400(1002)。"""
    goal, themes, _ = make_tree(db_session)
    ws = _make_workspace(db_session, themes[0], managed=False, status="未初始化")
    db_session.flush()

    resp = client.put(f"{_API}/workspaces/{ws.id}/link", json={"path": "/nonexistent-xyz"})
    assert resp.status_code == 400
    assert resp.json()["code"] == 1002


def test_workspaces_get_returns_detail(client, db_session):
    """GET /{id} -> 工作空间详情（H5 只读）。"""
    goal, themes, _ = make_tree(db_session)
    ws = _make_workspace(db_session, themes[0], managed=True, status="已就绪")
    db_session.flush()

    resp = client.get(f"{_API}/workspaces/{ws.id}")
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["workspace_id"] == ws.id
    assert data["managed"] is True
    assert data["status"] == "已就绪"


def test_workspaces_get_not_found_returns_404(client, db_session):
    resp = client.get(f"{_API}/workspaces/no-such-id")
    assert resp.status_code == 404
    assert resp.json()["code"] == 1001
