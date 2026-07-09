"""Story4A 单元测试：OpenCodeClient（mock httpx）。"""

from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.clients.opencode import OpenCodeClient
from app.models.agent_process import AgentProcess
from app.models.workspace import Workspace
from tests._factory import make_tree


def _setup_workspace(db):
    """创建 goal->theme->phase->task 树 + workspace。"""
    goal, themes, phases = make_tree(db, n_themes=1, phases_per_theme=1, tasks_per_phase=1)
    ws = Workspace(
        id=str(uuid4()),
        theme_id=themes[0].id,
        path=f"data/workspaces/{uuid4().hex[:8]}",
        managed=True,
        status="已就绪",
        type=themes[0].type,
    )
    db.add(ws)
    db.flush()
    return ws


def test_parse_port_range():
    """端口范围解析 10000-20000。"""
    lo, hi = OpenCodeClient._parse_port_range()
    assert lo == 10000
    assert hi == 20000


def test_allocate_port_finds_free(db_session):
    """分配第一个空闲端口。"""
    ws = _setup_workspace(db_session)
    # 占用 10000
    ap = AgentProcess(id=str(uuid4()), workspace_id=ws.id, port=10000, status="running")
    db_session.add(ap)
    db_session.flush()

    port = OpenCodeClient._allocate_port(db_session)
    assert port == 10001


def test_allocate_port_all_free(db_session):
    """无占用时分配 10000。"""
    _setup_workspace(db_session)
    port = OpenCodeClient._allocate_port(db_session)
    assert port == 10000


def test_dispatch_task_makes_http_post(db_session):
    """dispatch_task 发 HTTP POST 到 opencode serve。"""
    ws = _setup_workspace(db_session)
    task = {"task_id": "t1", "name": "test task"}
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"ok": True}
    mock_resp.raise_for_status = MagicMock()

    with patch("app.clients.opencode.httpx.post", return_value=mock_resp) as mock_post:
        client = OpenCodeClient(db_session)
        result = client.dispatch_task(ws.id, task, 10001)

    assert result == {"ok": True}
    mock_post.assert_called_once()
    call_args = mock_post.call_args
    assert "10001" in call_args.args[0]
    assert call_args.kwargs["json"] == task


def test_dispatch_pre_subtasks_calls_http(db_session):
    """dispatch_pre_subtasks 逐个 HTTP POST。"""
    subtasks = [
        {"id": "s1", "name": "sub1", "task_id": "t1"},
        {"id": "s2", "name": "sub2", "task_id": "t1"},
    ]
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()

    with patch("app.clients.opencode.httpx.post", return_value=mock_resp) as mock_post:
        client = OpenCodeClient(db_session)
        client.dispatch_pre_subtasks(subtasks)

    assert mock_post.call_count == 2


def test_start_agent_serve_creates_process(db_session):
    """start_agent_serve 创建 agent_processes 记录 + dispatch 首任务。"""
    ws = _setup_workspace(db_session)
    task = {"task_id": "t1", "name": "test"}
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"ok": True}
    mock_resp.raise_for_status = MagicMock()

    with patch("app.clients.opencode.httpx.post", return_value=mock_resp):
        client = OpenCodeClient(db_session)
        port = client.start_agent_serve(ws.id, task)

    assert port > 0
    ap = db_session.query(AgentProcess).filter_by(workspace_id=ws.id).one()
    assert ap.status == "running"
    assert ap.port == port


def test_start_agent_serve_reuses_running_process(db_session):
    """已有 running 进程时复用端口。"""
    ws = _setup_workspace(db_session)
    ap = AgentProcess(
        id=str(uuid4()),
        workspace_id=ws.id,
        port=10050,
        status="running",
    )
    db_session.add(ap)
    db_session.flush()

    client = OpenCodeClient(db_session)
    port = client.start_agent_serve(ws.id, None)
    assert port == 10050


def test_start_agent_serve_restarts_stopped_process(db_session):
    """stopped 进程重启：更新记录，分配新端口。"""
    ws = _setup_workspace(db_session)
    ap = AgentProcess(
        id=str(uuid4()),
        workspace_id=ws.id,
        port=10050,
        status="stopped",
    )
    db_session.add(ap)
    db_session.flush()

    client = OpenCodeClient(db_session)
    port = client.start_agent_serve(ws.id, None)
    assert port == 10000  # 10050 已释放（stopped 不占），分配第一个空闲
    db_session.refresh(ap)
    assert ap.status == "running"


def test_health_returns_true_when_responding(db_session):
    """health 检查返回 True 当 serve 响应 200。"""
    ws = _setup_workspace(db_session)
    ap = AgentProcess(id=str(uuid4()), workspace_id=ws.id, port=10001, status="running")
    db_session.add(ap)
    db_session.flush()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    with patch("app.clients.opencode.httpx.get", return_value=mock_resp):
        client = OpenCodeClient(db_session)
        assert client.health(ws.id) is True


def test_health_returns_false_when_no_process(db_session):
    """无 running 进程 -> False。"""
    ws = _setup_workspace(db_session)
    client = OpenCodeClient(db_session)
    assert client.health(ws.id) is False


def test_shutdown_updates_status(db_session):
    """shutdown 更新 agent_processes.status='stopped'。"""
    ws = _setup_workspace(db_session)
    ap = AgentProcess(id=str(uuid4()), workspace_id=ws.id, port=10001, status="running")
    db_session.add(ap)
    db_session.flush()

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    with patch("app.clients.opencode.httpx.post", return_value=mock_resp):
        client = OpenCodeClient(db_session)
        result = client.shutdown(ws.id)

    assert result is True
    db_session.refresh(ap)
    assert ap.status == "stopped"


def test_shutdown_returns_false_when_no_process(db_session):
    """无 running 进程 -> False。"""
    ws = _setup_workspace(db_session)
    client = OpenCodeClient(db_session)
    assert client.shutdown(ws.id) is False
