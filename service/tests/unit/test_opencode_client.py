"""Story4A 单元测试：OpenCodeClient（方案 B：全局单进程 + 多 session，mock httpx/subprocess）。"""

import subprocess
from unittest.mock import MagicMock, patch
from uuid import uuid4

import httpx
import pytest

from app.clients.opencode import OpenCodeClient
from app.config import settings
from app.core.exceptions import InternalError
from app.models.agent_process import AgentProcess
from app.models.task import Task
from app.models.workspace import Workspace
from tests._factory import make_tree


@pytest.fixture(autouse=True)
def _reset_serve_proc():
    """每个测试前重置全局 serve 进程单例，避免测试间污染。"""
    OpenCodeClient._proc = None
    yield
    OpenCodeClient._proc = None


def _setup_workspace(db):
    """创建 goal->theme->phase->task 树 + workspace，返回 (ws, task)。"""
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
    task = db.query(Task).filter_by(phase_id=phases[0].id).one()
    return ws, task


# ---- base_url ----


def test_base_url_uses_serve_port():
    """base_url property 由 opencode_serve_port 派生。"""
    client = OpenCodeClient()
    assert client.base_url == f"http://127.0.0.1:{settings.opencode_serve_port}"


# ---- start_serve / _wait_port ----


def test_start_serve_starts_subprocess():
    """start_serve 启动 opencode serve 子进程 + 等待端口就绪。"""
    mock_proc = MagicMock()
    mock_proc.poll.return_value = None  # 运行中
    mock_get = MagicMock(status_code=200)
    with (
        patch("app.clients.opencode.subprocess.Popen", return_value=mock_proc) as mock_popen,
        patch("app.clients.opencode.httpx.get", return_value=mock_get),
    ):
        client = OpenCodeClient()
        client.start_serve()

    mock_popen.assert_called_once()
    cmd = mock_popen.call_args.args[0]
    assert "opencode" in cmd
    assert "serve" in cmd
    assert str(settings.opencode_serve_port) in cmd
    assert OpenCodeClient._proc is mock_proc


def test_start_serve_idempotent_when_running():
    """serve 已运行（_proc.poll() is None）时不重复启动。"""
    mock_proc = MagicMock()
    mock_proc.poll.return_value = None  # 运行中
    OpenCodeClient._proc = mock_proc
    with (
        patch("app.clients.opencode.subprocess.Popen") as mock_popen,
        patch("app.clients.opencode.httpx.get") as mock_get,
    ):
        client = OpenCodeClient()
        client.start_serve()

    mock_popen.assert_not_called()
    mock_get.assert_not_called()


def test_wait_port_timeout_raises():
    """_wait_port 超时抛 InternalError（ConnectError 轮询至超时）。"""
    with patch("app.clients.opencode.httpx.get", side_effect=httpx.ConnectError("refused")):
        with pytest.raises(InternalError, match="启动超时"):
            OpenCodeClient._wait_port(settings.opencode_serve_port, timeout=1)


def test_wait_port_raises_on_http_error():
    """P1-2：HTTPStatusError（服务起来了但报错）应立即抛出，不轮询。"""
    mock_resp = MagicMock(status_code=500)
    http_error = httpx.HTTPStatusError("Server Error", request=MagicMock(), response=mock_resp)
    with patch("app.clients.opencode.httpx.get", side_effect=http_error):
        with pytest.raises(InternalError, match="启动异常"):
            OpenCodeClient._wait_port(settings.opencode_serve_port, timeout=5)


# ---- _ensure_session ----


def test_ensure_session_reuses_existing(db_session):
    """已有 session_id 的 agent_process -> 复用，不调 HTTP。"""
    ws, _ = _setup_workspace(db_session)
    ap = AgentProcess(
        id=str(uuid4()),
        workspace_id=ws.id,
        port=settings.opencode_serve_port,
        status="running",
        session_id="ses_existing",
    )
    db_session.add(ap)
    db_session.flush()

    with patch("app.clients.opencode.httpx.post") as mock_post:
        client = OpenCodeClient(db_session)
        sid = client._ensure_session(ws.id)

    assert sid == "ses_existing"
    mock_post.assert_not_called()


def test_ensure_session_creates_new(db_session):
    """无 session_id -> POST /session 建会话，存 agent_processes.session_id。

    P0 铁律 §3#3：HTTP 在事务外（事务1 commit 占位 -> 事务外 HTTP -> 事务2 回填）。
    """
    ws, _ = _setup_workspace(db_session)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"id": "ses_new", "directory": ws.path}
    mock_resp.raise_for_status = MagicMock()

    with patch("app.clients.opencode.httpx.post", return_value=mock_resp) as mock_post:
        client = OpenCodeClient(db_session)
        sid = client._ensure_session(ws.id)

    assert sid == "ses_new"
    mock_post.assert_called_once()
    # 验证 POST /session 请求体
    call = mock_post.call_args
    assert "/session" in call.args[0]
    assert call.kwargs["json"]["directory"] is not None
    # agent_processes 记录已回填 session_id
    ap = db_session.query(AgentProcess).filter_by(workspace_id=ws.id).one()
    assert ap.session_id == "ses_new"
    assert ap.status == "running"


def test_ensure_session_returns_none_when_no_workspace(db_session):
    """workspace 不存在 -> None。"""
    with patch("app.clients.opencode.httpx.post") as mock_post:
        client = OpenCodeClient(db_session)
        assert client._ensure_session("nonexistent") is None

    mock_post.assert_not_called()


def test_ensure_session_updates_existing_record(db_session):
    """已有 stopped 记录（无 session_id）-> 更新而非新建。"""
    ws, _ = _setup_workspace(db_session)
    ap = AgentProcess(
        id=str(uuid4()),
        workspace_id=ws.id,
        port=settings.opencode_serve_port,
        status="stopped",
    )
    db_session.add(ap)
    db_session.flush()

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"id": "ses_updated"}
    mock_resp.raise_for_status = MagicMock()

    with patch("app.clients.opencode.httpx.post", return_value=mock_resp):
        client = OpenCodeClient(db_session)
        sid = client._ensure_session(ws.id)

    assert sid == "ses_updated"
    db_session.refresh(ap)
    assert ap.session_id == "ses_updated"
    assert ap.status == "running"


def test_ensure_session_http_failure_returns_none(db_session):
    """P0 铁律 §3#3：HTTP 失败返回 None，但占位 agent_processes 记录已提交。

    事务1 已 commit（session_id=None 占位），事务外 HTTP 失败 -> 返回 None。
    DB 有占位记录（session_id=None, status=running），下次 _ensure_session 会重试。
    """
    ws, _ = _setup_workspace(db_session)

    with patch("app.clients.opencode.httpx.post", side_effect=httpx.ConnectError("refused")):
        client = OpenCodeClient(db_session)
        sid = client._ensure_session(ws.id)

    assert sid is None
    # 占位记录已提交（session_id=None）
    ap = db_session.query(AgentProcess).filter_by(workspace_id=ws.id).one()
    assert ap.session_id is None
    assert ap.status == "running"


def test_ensure_session_http_outside_transaction(db_session):
    """P0 铁律 §3#3：HTTP 在事务外。验证 commit 先于 HTTP 调用。

    事务1 commit（占位 session_id=None）-> 事务外 HTTP -> 事务2 commit（回填）。
    验证：HTTP 调用时，占位记录已在 DB（session_id=None）。
    """
    ws, _ = _setup_workspace(db_session)
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"id": "ses_p0"}
    mock_resp.raise_for_status = MagicMock()

    http_call_order = []

    def _track_http(*args, **kwargs):
        # HTTP 被调用时，查 DB：占位记录应已存在（session_id=None）
        ap = db_session.query(AgentProcess).filter_by(workspace_id=ws.id).first()
        http_call_order.append(ap.session_id if ap else "NO_RECORD")
        return mock_resp

    with patch("app.clients.opencode.httpx.post", side_effect=_track_http):
        client = OpenCodeClient(db_session)
        client._ensure_session(ws.id)

    # HTTP 调用时 session_id 应为 None（占位已 commit，回填还没发生）
    assert http_call_order == [None]


# ---- dispatch_task ----


def test_dispatch_task_parses_result(db_session):
    """dispatch_task POST /session/{id}/message，解析 result/finish/tokens。

    P1-1：合并所有 text part（多段输出不截断）。
    """
    ws, _ = _setup_workspace(db_session)
    ap = AgentProcess(
        id=str(uuid4()),
        workspace_id=ws.id,
        port=settings.opencode_serve_port,
        status="running",
        session_id="ses_123",
    )
    db_session.add(ap)
    db_session.flush()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "info": {"finish": "stop", "tokens": {"input": 10, "output": 5}},
        "parts": [
            {"type": "step-start"},
            {"type": "text", "text": "第一段"},
            {"type": "text", "text": "第二段"},
            {"type": "step-finish", "reason": "stop"},
        ],
    }

    with patch("app.clients.opencode.httpx.post", return_value=mock_resp) as mock_post:
        client = OpenCodeClient(db_session)
        result = client.dispatch_task(ws.id, {"task_id": "t1", "name": "test task"})

    assert result["finish"] == "stop"
    # P1-1：多段 text 合并
    assert result["result"] == "第一段第二段"
    assert result["tokens"] == {"input": 10, "output": 5}
    # 验证请求路径含 session_id
    call = mock_post.call_args
    assert "/session/ses_123/message" in call.args[0]
    # 验证请求体 parts（prompt 取 name）
    parts = call.kwargs["json"]["parts"]
    assert parts[0]["text"] == "test task"


def test_dispatch_task_no_session_raises(db_session):
    """无可用 session（workspace 不存在）-> raise InternalError。"""
    with patch("app.clients.opencode.httpx.post"):
        client = OpenCodeClient(db_session)
        with pytest.raises(InternalError, match="无可用 session"):
            client.dispatch_task("nonexistent", {"name": "test"})


def test_dispatch_task_port_param_ignored(db_session):
    """dispatch_task 的 port 参数被忽略（方案 B 全局端口，兼容旧调用方 _retry_dispatch）。"""
    ws, _ = _setup_workspace(db_session)
    ap = AgentProcess(
        id=str(uuid4()),
        workspace_id=ws.id,
        port=settings.opencode_serve_port,
        status="running",
        session_id="ses_x",
    )
    db_session.add(ap)
    db_session.flush()

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"info": {"finish": "stop"}, "parts": []}

    with patch("app.clients.opencode.httpx.post", return_value=mock_resp):
        client = OpenCodeClient(db_session)
        # 传 port（旧调用方 _retry_dispatch 传 ap.port），应被忽略不报错
        result = client.dispatch_task(ws.id, {"name": "t"}, port=9999)

    assert result["finish"] == "stop"


# ---- _get_workspace_id_for_subtask ----


def test_get_workspace_id_for_subtask(db_session):
    """从 subtask.task_id 反查 workspace_id。"""
    ws, task = _setup_workspace(db_session)
    client = OpenCodeClient(db_session)
    result = client._get_workspace_id_for_subtask({"task_id": task.id})
    assert result == ws.id


def test_get_workspace_id_for_subtask_no_task_id():
    """subtask 无 task_id -> None。"""
    client = OpenCodeClient()
    assert client._get_workspace_id_for_subtask({}) is None


# ---- dispatch_pre/post_subtasks ----


def test_dispatch_pre_subtasks_sends_messages(db_session):
    """dispatch_pre_subtasks 逐个反查 workspace + 发 message。"""
    ws, task = _setup_workspace(db_session)
    subtasks = [
        {"id": "s1", "name": "前置1", "task_id": task.id},
        {"id": "s2", "name": "前置2", "task_id": task.id},
    ]
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"info": {"finish": "stop"}, "parts": []}

    with (
        patch.object(OpenCodeClient, "start_serve"),
        patch.object(OpenCodeClient, "_ensure_session", return_value="ses_pre"),
        patch("app.clients.opencode.httpx.post", return_value=mock_resp) as mock_post,
    ):
        client = OpenCodeClient(db_session)
        client.dispatch_pre_subtasks(subtasks)

    assert mock_post.call_count == 2
    for call in mock_post.call_args_list:
        assert "/session/ses_pre/message" in call.args[0]


def test_dispatch_post_subtasks_sends_messages(db_session):
    """dispatch_post_subtasks 逐个反查 workspace + 发 message。"""
    ws, task = _setup_workspace(db_session)
    subtasks = [{"id": "s1", "name": "后置1", "task_id": task.id}]
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"info": {"finish": "stop"}, "parts": []}

    with (
        patch.object(OpenCodeClient, "start_serve"),
        patch.object(OpenCodeClient, "_ensure_session", return_value="ses_post"),
        patch("app.clients.opencode.httpx.post", return_value=mock_resp) as mock_post,
    ):
        client = OpenCodeClient(db_session)
        client.dispatch_post_subtasks(subtasks)

    mock_post.assert_called_once()
    call = mock_post.call_args
    assert "/session/ses_post/message" in call.args[0]


def test_dispatch_pre_subtasks_skips_when_no_workspace(db_session):
    """subtask 的 task_id 无法反查 workspace -> 跳过（不发 HTTP）。"""
    subtasks = [{"id": "s1", "name": "sub1", "task_id": "nonexistent_task"}]

    with (
        patch.object(OpenCodeClient, "start_serve") as mock_start,
        patch("app.clients.opencode.httpx.post") as mock_post,
    ):
        client = OpenCodeClient(db_session)
        client.dispatch_pre_subtasks(subtasks)

    mock_start.assert_not_called()
    mock_post.assert_not_called()


# ---- start_agent_serve ----


def test_start_agent_serve_returns_port(db_session):
    """start_agent_serve 成功返回 serve 端口。"""
    ws, _ = _setup_workspace(db_session)
    with (
        patch.object(OpenCodeClient, "start_serve"),
        patch.object(OpenCodeClient, "_ensure_session", return_value="ses_1"),
    ):
        client = OpenCodeClient(db_session)
        port = client.start_agent_serve(ws.id, None)

    assert port == settings.opencode_serve_port


def test_start_agent_serve_dispatches_first_task(db_session):
    """有 task 时 dispatch 首任务。"""
    ws, _ = _setup_workspace(db_session)
    with (
        patch.object(OpenCodeClient, "start_serve"),
        patch.object(OpenCodeClient, "_ensure_session", return_value="ses_1"),
        patch.object(OpenCodeClient, "dispatch_task") as mock_dispatch,
    ):
        client = OpenCodeClient(db_session)
        port = client.start_agent_serve(ws.id, {"task_id": "t1", "name": "test"})

    assert port == settings.opencode_serve_port
    mock_dispatch.assert_called_once()


def test_start_agent_serve_returns_neg1_when_no_session(db_session):
    """_ensure_session 返回 None -> 返回 -1。"""
    ws, _ = _setup_workspace(db_session)
    with (
        patch.object(OpenCodeClient, "start_serve"),
        patch.object(OpenCodeClient, "_ensure_session", return_value=None),
    ):
        client = OpenCodeClient(db_session)
        port = client.start_agent_serve(ws.id, None)

    assert port == -1


def test_start_agent_serve_dispatch_failure_returns_port(db_session):
    """P0 铁律 §3#3：dispatch 首任务失败不影响 port 返回（agent_processes 已提交）。"""
    ws, _ = _setup_workspace(db_session)
    with (
        patch.object(OpenCodeClient, "start_serve"),
        patch.object(OpenCodeClient, "_ensure_session", return_value="ses_1"),
        patch.object(OpenCodeClient, "dispatch_task", side_effect=Exception("HTTP failed")),
    ):
        client = OpenCodeClient(db_session)
        port = client.start_agent_serve(ws.id, {"task_id": "t1", "name": "test"})

    assert port == settings.opencode_serve_port


# ---- health ----


def test_health_returns_true_when_responding():
    """GET /session 响应 200 -> True。"""
    mock_resp = MagicMock(status_code=200)
    with patch("app.clients.opencode.httpx.get", return_value=mock_resp):
        client = OpenCodeClient()
        assert client.health("ws1") is True


def test_health_returns_false_on_error():
    """HTTP 异常 -> False。"""
    with patch("app.clients.opencode.httpx.get", side_effect=ConnectionError("refused")):
        client = OpenCodeClient()
        assert client.health("ws1") is False


# ---- shutdown ----


def test_shutdown_marks_stopped(db_session):
    """shutdown 标记 agent_processes.status='stopped'（全局进程保留）。"""
    ws, _ = _setup_workspace(db_session)
    ap = AgentProcess(
        id=str(uuid4()),
        workspace_id=ws.id,
        port=settings.opencode_serve_port,
        status="running",
        session_id="ses_x",
    )
    db_session.add(ap)
    db_session.flush()

    client = OpenCodeClient(db_session)
    result = client.shutdown(ws.id)

    assert result is True
    db_session.refresh(ap)
    assert ap.status == "stopped"


def test_shutdown_returns_false_when_no_process(db_session):
    """无 running 进程 -> False。"""
    ws, _ = _setup_workspace(db_session)
    client = OpenCodeClient(db_session)
    assert client.shutdown(ws.id) is False


def test_shutdown_no_http_call(db_session):
    """方案 B：shutdown 纯 DB（全局进程保留），不发 HTTP。"""
    ws, _ = _setup_workspace(db_session)
    ap = AgentProcess(
        id=str(uuid4()),
        workspace_id=ws.id,
        port=settings.opencode_serve_port,
        status="running",
        session_id="ses_x",
    )
    db_session.add(ap)
    db_session.flush()

    with patch("app.clients.opencode.httpx.post") as mock_post:
        client = OpenCodeClient(db_session)
        client.shutdown(ws.id)

    mock_post.assert_not_called()


# ---- delete_session（D26：3 次不通过退 session，全局 serve 保留）----


def test_delete_session_calls_delete_api(db_session):
    """delete_session 调 DELETE /session/{id} 退 session（D26 方案 B）。"""
    ws, _ = _setup_workspace(db_session)
    ap = AgentProcess(
        id=str(uuid4()),
        workspace_id=ws.id,
        port=settings.opencode_serve_port,
        status="running",
        session_id="ses_to_delete",
    )
    db_session.add(ap)
    db_session.flush()

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()

    with patch("app.clients.opencode.httpx.delete", return_value=mock_resp) as mock_delete:
        client = OpenCodeClient(db_session)
        result = client.delete_session(ws.id)

    assert result is True
    mock_delete.assert_called_once()
    call = mock_delete.call_args
    assert "/session/ses_to_delete" in call.args[0]


def test_delete_session_clears_session_id_and_status(db_session):
    """delete_session 后 agent_processes.session_id=None, status=stopped。"""
    ws, _ = _setup_workspace(db_session)
    ap = AgentProcess(
        id=str(uuid4()),
        workspace_id=ws.id,
        port=settings.opencode_serve_port,
        status="running",
        session_id="ses_x",
    )
    db_session.add(ap)
    db_session.flush()

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()

    with patch("app.clients.opencode.httpx.delete", return_value=mock_resp):
        client = OpenCodeClient(db_session)
        client.delete_session(ws.id)

    db_session.refresh(ap)
    assert ap.session_id is None
    assert ap.status == "stopped"


def test_delete_session_preserves_global_serve(db_session):
    """方案 B（D26）：退 session 不 terminate 全局 serve 进程。"""
    ws, _ = _setup_workspace(db_session)
    ap = AgentProcess(
        id=str(uuid4()),
        workspace_id=ws.id,
        port=settings.opencode_serve_port,
        status="running",
        session_id="ses_y",
    )
    db_session.add(ap)
    db_session.flush()

    mock_proc = MagicMock()
    mock_proc.poll.return_value = None  # 运行中
    OpenCodeClient._proc = mock_proc

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()

    with patch("app.clients.opencode.httpx.delete", return_value=mock_resp):
        client = OpenCodeClient(db_session)
        client.delete_session(ws.id)

    # 全局 serve 进程未被 terminate，_proc 保留
    mock_proc.terminate.assert_not_called()
    assert OpenCodeClient._proc is mock_proc


def test_delete_session_returns_false_when_no_record(db_session):
    """无 agent_process 记录 -> False，不发 HTTP。"""
    ws, _ = _setup_workspace(db_session)

    with patch("app.clients.opencode.httpx.delete") as mock_delete:
        client = OpenCodeClient(db_session)
        result = client.delete_session(ws.id)

    assert result is False
    mock_delete.assert_not_called()


def test_delete_session_returns_false_when_session_id_none(db_session):
    """agent_process 存在但 session_id=None -> False，不发 HTTP。"""
    ws, _ = _setup_workspace(db_session)
    ap = AgentProcess(
        id=str(uuid4()),
        workspace_id=ws.id,
        port=settings.opencode_serve_port,
        status="running",
        session_id=None,
    )
    db_session.add(ap)
    db_session.flush()

    with patch("app.clients.opencode.httpx.delete") as mock_delete:
        client = OpenCodeClient(db_session)
        result = client.delete_session(ws.id)

    assert result is False
    mock_delete.assert_not_called()


def test_delete_session_http_failure_returns_false(db_session):
    """HTTP DELETE 失败 -> 返回 False，不抛（失败非阻塞）。

    P1 修复（DB 先清）：HTTP 失败时 DB session_id 已 None、status=stopped（事务1
    在 HTTP 之前 commit）。下次 _ensure_session 必走重建路径，不复用旧 session_id
    导致 404 阻断。opencode session 变孤儿（serve 退出自然清理，可接受）。
    """
    ws, _ = _setup_workspace(db_session)
    ap = AgentProcess(
        id=str(uuid4()),
        workspace_id=ws.id,
        port=settings.opencode_serve_port,
        status="running",
        session_id="ses_fail",
    )
    db_session.add(ap)
    db_session.flush()

    with patch("app.clients.opencode.httpx.delete", side_effect=httpx.ConnectError("refused")):
        client = OpenCodeClient(db_session)
        result = client.delete_session(ws.id)

    assert result is False
    # DB 已在事务1清完（HTTP 前 commit），无论 HTTP 成败 DB 均 None
    db_session.refresh(ap)
    assert ap.session_id is None
    assert ap.status == "stopped"


def test_delete_session_db_cleared_before_http(db_session):
    """P1 修复验证：DB session_id 在 HTTP DELETE 调用前已清为 None。

    顺序：事务1 commit（session_id=None + stopped）-> 事务外 HTTP DELETE。
    验证：HTTP 被调用时，DB session_id 应为 None（已 commit，无 404 阻断风险）。
    """
    ws, _ = _setup_workspace(db_session)
    ap = AgentProcess(
        id=str(uuid4()),
        workspace_id=ws.id,
        port=settings.opencode_serve_port,
        status="running",
        session_id="ses_order",
    )
    db_session.add(ap)
    db_session.flush()

    http_call_db_state = []

    def _track_http(*args, **kwargs):
        # HTTP 被调用时查 DB：session_id 应已 None（事务1 已 commit）
        db_session.refresh(ap)
        http_call_db_state.append(ap.session_id)
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        return mock_resp

    with patch("app.clients.opencode.httpx.delete", side_effect=_track_http):
        client = OpenCodeClient(db_session)
        client.delete_session(ws.id)

    # HTTP 调用时 DB session_id 应为 None（事务1 已 commit 清理）
    assert http_call_db_state == [None]


# ---- shutdown_serve（P1-3：全局进程清理）----


def test_shutdown_serve_terminates_running_process():
    """shutdown_serve terminate 运行中的全局 serve 子进程。"""
    mock_proc = MagicMock()
    mock_proc.poll.return_value = None  # 运行中
    mock_proc.wait.return_value = 0
    OpenCodeClient._proc = mock_proc

    OpenCodeClient.shutdown_serve()

    mock_proc.terminate.assert_called_once()
    mock_proc.wait.assert_called_once()
    assert OpenCodeClient._proc is None


def test_shutdown_serve_kills_on_timeout():
    """shutdown_serve terminate 超时后 kill。"""
    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    # 第一次 wait(timeout=10) 超时，第二次 wait()（kill 后）返回 0
    mock_proc.wait.side_effect = [subprocess.TimeoutExpired(cmd="opencode", timeout=10), 0]
    OpenCodeClient._proc = mock_proc

    OpenCodeClient.shutdown_serve()

    mock_proc.terminate.assert_called_once()
    mock_proc.kill.assert_called_once()
    assert mock_proc.wait.call_count == 2
    assert OpenCodeClient._proc is None


def test_shutdown_serve_noop_when_no_proc():
    """无全局进程（_proc=None）-> no-op。"""
    OpenCodeClient._proc = None
    OpenCodeClient.shutdown_serve()  # 不抛异常
    assert OpenCodeClient._proc is None


def test_shutdown_serve_noop_when_already_exited():
    """进程已退出（poll() 非 None）-> 仅清理 _proc，不 terminate。"""
    mock_proc = MagicMock()
    mock_proc.poll.return_value = 1  # 已退出
    OpenCodeClient._proc = mock_proc

    OpenCodeClient.shutdown_serve()

    mock_proc.terminate.assert_not_called()
    assert OpenCodeClient._proc is None
