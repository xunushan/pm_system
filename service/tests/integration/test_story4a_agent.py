"""Story4A 集成测试：智能体执行全链路（API + DB）+ webhook 回调。

验收要点（doc/01 S4A）：
  - GET /tasks/{id} 详情含 executor
  - POST /confirm-complete 完成任务 + 重启 serve（mock）
  - POST /output/confirm 验收通过 + 即时级联（mock）
  - POST /output/reject 重试 / 超次两路径
  - POST /api/callback/opencode/output 记录产出
  - POST /api/callback/opencode/timeout 超时告警
  - webhook story4A 验收通过 / 需要修改
  - 3次重试 -> manual_intervention，不改状态
"""

from datetime import date
from unittest.mock import patch
from uuid import uuid4

from app.models.agent_process import AgentProcess
from app.models.task import Task
from app.models.workspace import Workspace
from app.models.workspace_progress import WorkspaceProgress
from app.services import task_app_svc
from tests._factory import make_tree

_API = "/api/v1"
_CALLBACK = "/api/callback"
_WEBHOOK = "/webhook/feishu/card"
_TODAY = date(2026, 7, 9)


def _make_full_tree(db, *, theme_type="dev", tasks_per_phase=2, task_executor="agent"):
    """建 goal->theme->phase->task + workspace 树。"""
    goal, themes, phases = make_tree(
        db, n_themes=1, phases_per_theme=1, tasks_per_phase=tasks_per_phase
    )
    themes[0].type = theme_type
    phases[0].status = "进行中"
    phases[0].activated_at = _TODAY
    ws = Workspace(
        id=str(uuid4()),
        theme_id=themes[0].id,
        path=f"data/workspaces/{uuid4().hex[:8]}",
        managed=True,
        status="已就绪",
        type=theme_type,
    )
    db.add(ws)
    db.flush()
    tasks = db.query(Task).filter_by(phase_id=phases[0].id).all()
    for t in tasks:
        t.executor = task_executor
    db.flush()
    return goal, themes, phases, ws, tasks


# ===== GET /tasks/{taskId} =====


def test_get_task_detail(client, db_session):
    """GET /tasks/{id} 返回任务详情含 executor。"""
    goal, themes, phases, ws, tasks = _make_full_tree(db_session)
    db_session.flush()

    resp = client.get(f"{_API}/tasks/{tasks[0].id}")
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["task_id"] == tasks[0].id
    assert data["executor"] == "agent"
    assert data["status"] == "待执行"


def test_get_task_not_found(client, db_session):
    """GET /tasks/{id} 不存在 -> 404。"""
    resp = client.get(f"{_API}/tasks/nonexistent")
    assert resp.status_code == 404
    assert resp.json()["code"] == 1001


# ===== POST /tasks/{taskId}/confirm-complete =====


def test_confirm_complete_api(client, db_session):
    """POST /confirm-complete 完成任务 + 重启 serve（mock）。"""
    goal, themes, phases, ws, tasks = _make_full_tree(db_session)
    task = tasks[0]
    next_task = tasks[1]
    next_task.executor = "agent"
    next_task.status = "待执行"
    db_session.flush()

    with (
        patch.object(task_app_svc.state_machine, "validate_transition"),
        patch.object(task_app_svc.cascade, "cascade_status"),
        patch.object(task_app_svc, "emit"),
        patch.object(task_app_svc.OpenCodeClient, "shutdown"),
        patch.object(task_app_svc.OpenCodeClient, "start_agent_serve", return_value=10002),
    ):
        resp = client.post(
            f"{_API}/tasks/{task.id}/confirm-complete",
            json={"user_id": "u1"},
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["status"] == "已完成"
    assert data["opencode_restarted"] is True
    assert data["next_agent_task"] == next_task.id


def test_confirm_complete_already_done_400(client, db_session):
    """已完成任务 -> 400。"""
    goal, themes, phases, ws, tasks = _make_full_tree(db_session)
    tasks[0].status = "已完成"
    db_session.flush()

    resp = client.post(
        f"{_API}/tasks/{tasks[0].id}/confirm-complete",
        json={"user_id": "u1"},
    )
    assert resp.status_code == 400


# ===== POST /tasks/{taskId}/output/confirm =====


def test_output_confirm_api(client, db_session):
    """POST /output/confirm 验收通过。"""
    goal, themes, phases, ws, tasks = _make_full_tree(db_session)
    task = tasks[0]
    db_session.flush()

    with (
        patch.object(task_app_svc.state_machine, "validate_transition"),
        patch.object(task_app_svc.cascade, "cascade_status"),
        patch.object(task_app_svc, "emit"),
    ):
        resp = client.post(
            f"{_API}/tasks/{task.id}/output/confirm",
            json={"user_id": "u1", "workspace_progress_ids": []},
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["status"] == "已完成"

    db_session.refresh(task)
    assert task.status == "已完成"


# ===== POST /tasks/{taskId}/output/reject =====


def test_output_reject_retry_api(client, db_session):
    """POST /output/reject 重试路径（retry_count < 3）。"""
    goal, themes, phases, ws, tasks = _make_full_tree(db_session)
    task = tasks[0]
    task.retry_count = 0
    # 需要 running agent_process 才能找到端口
    ap = AgentProcess(id=str(uuid4()), workspace_id=ws.id, port=10001, status="running")
    db_session.add(ap)
    db_session.flush()

    with (
        patch.object(task_app_svc.OpenCodeClient, "dispatch_task"),
        patch.object(task_app_svc, "set_task_timeout"),
    ):
        resp = client.post(
            f"{_API}/tasks/{task.id}/output/reject",
            json={"user_id": "u1", "feedback": "字段不全"},
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["action"] == "retry"
    assert data["retry_count"] == 1
    assert data["max_retry"] == 3


def test_output_reject_manual_intervention_api(client, db_session):
    """POST /output/reject 超次路径（retry_count >= 3）。"""
    goal, themes, phases, ws, tasks = _make_full_tree(db_session)
    task = tasks[0]
    task.retry_count = 3
    db_session.flush()

    with (
        patch.object(task_app_svc.OpenCodeClient, "shutdown", return_value=True),
        patch.object(task_app_svc.FeishuClient, "send_text"),
    ):
        resp = client.post(
            f"{_API}/tasks/{task.id}/output/reject",
            json={"user_id": "u1", "feedback": "多次不过"},
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["action"] == "manual_intervention"
    assert data["opencode_stopped"] is True
    assert data["workspace_path"] is not None

    # 3次不通过不改状态
    db_session.refresh(task)
    assert task.status == "待执行"


# ===== POST /api/callback/opencode/output =====


def test_opencode_output_callback(client, db_session):
    """POST /api/callback/opencode/output 记录产出。"""
    goal, themes, phases, ws, tasks = _make_full_tree(db_session)
    task = tasks[0]
    db_session.flush()

    with (
        patch.object(task_app_svc, "del_task_timeout"),
        patch.object(task_app_svc.FeishuClient, "send_card"),
        patch.object(task_app_svc.FeishuClient, "send_file"),
    ):
        resp = client.post(
            f"{_CALLBACK}/opencode/output",
            json={
                "task_id": task.id,
                "workspace_id": ws.id,
                "outputs": [
                    {
                        "file_path": "docs/schema-v1.md",
                        "file_type": "design",
                        "summary": "Schema 设计",
                    },
                    {
                        "file_path": "src/schema.py",
                        "file_type": "code",
                    },
                ],
                "exit_code": 0,
                "duration": 3600,
            },
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["received"] is True
    assert data["progress_count"] == 2

    wps = db_session.query(WorkspaceProgress).filter_by(task_id=task.id).all()
    assert len(wps) == 2


# ===== POST /api/callback/opencode/timeout =====


def test_opencode_timeout_callback(client, db_session):
    """POST /api/callback/opencode/timeout 超时告警。"""
    with patch.object(task_app_svc.FeishuClient, "send_text"):
        resp = client.post(
            f"{_CALLBACK}/opencode/timeout",
            json={
                "task_id": "task_001",
                "workspace_id": "ws_001",
                "timeout_at": "2026-07-09T10:00:00Z",
                "expected_callback": "opencode/output",
            },
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["alert_sent"] is True


# ===== webhook story4A =====


def test_webhook_story4a_confirm(client, db_session):
    """webhook story4A_验收通过 -> output_confirm。"""
    goal, themes, phases, ws, tasks = _make_full_tree(db_session)
    task = tasks[0]
    db_session.flush()

    with (
        patch.object(task_app_svc.state_machine, "validate_transition"),
        patch.object(task_app_svc.cascade, "cascade_status"),
        patch.object(task_app_svc, "emit"),
    ):
        payload = {
            "action": {
                "value": {
                    "action_id": "story4A_验收通过",
                    "task_id": task.id,
                    "user_id": "u1",
                    "workspace_progress_ids": [],
                }
            }
        }
        resp = client.post(_WEBHOOK, json=payload)

    assert resp.status_code == 200, resp.text
    assert resp.json()["code"] == 0
    db_session.refresh(task)
    assert task.status == "已完成"


def test_webhook_story4a_reject(client, db_session):
    """webhook story4A_需要修改 -> output_reject。"""
    goal, themes, phases, ws, tasks = _make_full_tree(db_session)
    task = tasks[0]
    task.retry_count = 0
    ap = AgentProcess(id=str(uuid4()), workspace_id=ws.id, port=10001, status="running")
    db_session.add(ap)
    db_session.flush()

    with (
        patch.object(task_app_svc.OpenCodeClient, "dispatch_task"),
        patch.object(task_app_svc, "set_task_timeout"),
    ):
        payload = {
            "action": {
                "value": {
                    "action_id": "story4A_需要修改",
                    "task_id": task.id,
                    "user_id": "u1",
                    "feedback": "缺少字段",
                }
            }
        }
        resp = client.post(_WEBHOOK, json=payload)

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["action"] == "retry"
    assert data["retry_count"] == 1


# ===== 边界：3次重试 -> manual_intervention =====


def test_three_retries_then_manual_intervention(client, db_session):
    """连续 3 次重试后第 4 次 -> manual_intervention。"""
    goal, themes, phases, ws, tasks = _make_full_tree(db_session)
    task = tasks[0]
    ap = AgentProcess(id=str(uuid4()), workspace_id=ws.id, port=10001, status="running")
    db_session.add(ap)
    db_session.flush()

    body = {"user_id": "u1", "feedback": "不过"}

    with (
        patch.object(task_app_svc.OpenCodeClient, "dispatch_task"),
        patch.object(task_app_svc, "set_task_timeout"),
        patch.object(task_app_svc.OpenCodeClient, "shutdown", return_value=True),
        patch.object(task_app_svc.FeishuClient, "send_text"),
    ):
        # 第 1-3 次：retry
        for i in range(1, 4):
            resp = client.post(
                f"{_API}/tasks/{task.id}/output/reject",
                json=body,
            )
            assert resp.status_code == 200
            data = resp.json()["data"]
            assert data["action"] == "retry"
            assert data["retry_count"] == i

        # 第 4 次：manual_intervention
        resp = client.post(
            f"{_API}/tasks/{task.id}/output/reject",
            json=body,
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["action"] == "manual_intervention"
        assert data["retry_count"] == 3

    # 状态始终不变
    db_session.refresh(task)
    assert task.status == "待执行"
