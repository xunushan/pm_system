"""Story4B 集成测试：complete + post-confirm + subtask CRUD + webhook（API + DB）。

验收要点（doc/01 S4B）：
  - complete：标记完成 + 即时级联 + 审计（forward）+ cascade 响应字段
  - complete：已完成 -> 409；不存在 -> 404；已暂停 -> 400
  - post-confirm：INSERT 后置 + 异步触发（mock opencode）；全取消不插入
  - post-confirm：非 human executor 拒绝；task 未完成拒绝
  - subtask CRUD：POST/GET/PATCH
  - webhook story4B 后置回调
"""

from unittest.mock import patch

from sqlalchemy.orm import sessionmaker

from app.models.status_change_log import StatusChangeLog
from app.models.subtask import Subtask
from app.models.task import Task
from app.services import task_app_svc
from tests._factory import make_tree

_API = "/api/v1"
_WEBHOOK = "/webhook/feishu/card"


def _activate_and_get_task(db_session, *, executor="human", tasks_per_phase=1):
    """建树 + 激活 phase/theme/goal + 返回 task（待执行）。"""
    goal, themes, phases = make_tree(db_session, tasks_per_phase=tasks_per_phase)
    goal.status = "进行中"
    themes[0].status = "进行中"
    phases[0].status = "进行中"
    task = (
        db_session.query(Task)
        .filter(Task.phase_id == phases[0].id)
        .order_by(Task.sort_order)
        .first()
    )
    task.executor = executor
    db_session.flush()
    return goal, themes, phases, task


# ===== POST /tasks/{taskId}/complete =====


def test_complete_task_full_flow(client, db_session):
    """POST /tasks/{id}/complete：标记完成 + 级联 + 审计 + cascade 响应。"""
    goal, themes, phases, task = _activate_and_get_task(db_session)

    resp = client.post(f"{_API}/tasks/{task.id}/complete", json={"user_id": "user_001"})

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["task_id"] == task.id
    assert data["status"] == "已完成"
    assert data["cascade"]["phase_completed"] is True
    assert data["cascade"]["theme_completed"] is True
    assert data["cascade"]["goal_completed"] is True

    # DB 验证
    db_session.flush()
    assert task.status == "已完成"
    assert task.completed_at is not None
    assert phases[0].status == "已完成"
    assert themes[0].status == "已完成"
    assert goal.status == "已完成"

    # 审计：1 forward(task) + 3 cascade(phase, theme, goal)
    assert db_session.query(StatusChangeLog).filter_by(change_type="forward").count() == 1
    assert db_session.query(StatusChangeLog).filter_by(change_type="cascade").count() == 3


def test_complete_already_completed_returns_409(client, db_session):
    """已完成任务再 complete -> 409。"""
    goal, themes, phases, task = _activate_and_get_task(db_session)
    task.status = "已完成"
    db_session.flush()

    resp = client.post(f"{_API}/tasks/{task.id}/complete", json={"user_id": "u1"})
    assert resp.status_code == 409
    assert resp.json()["code"] == 1003


def test_complete_not_found_returns_404(client, db_session):
    resp = client.post(f"{_API}/tasks/no-such-id/complete", json={"user_id": "u1"})
    assert resp.status_code == 404
    assert resp.json()["code"] == 1001


def test_complete_paused_returns_400(client, db_session):
    """已暂停任务 complete -> 400。"""
    goal, themes, phases, task = _activate_and_get_task(db_session)
    task.status = "已暂停"
    db_session.flush()

    resp = client.post(f"{_API}/tasks/{task.id}/complete", json={"user_id": "u1"})
    assert resp.status_code == 400
    assert resp.json()["code"] == 1002


def test_complete_partial_no_cascade(client, db_session):
    """phase 下多 task，完成 1 个 -> phase 不级联完成。"""
    goal, themes, phases, task = _activate_and_get_task(db_session, tasks_per_phase=2)

    resp = client.post(f"{_API}/tasks/{task.id}/complete", json={"user_id": "u1"})

    assert resp.status_code == 200
    assert resp.json()["data"]["cascade"]["phase_completed"] is False


# ===== POST /tasks/{taskId}/post-confirm =====


def test_post_confirm_full_flow(client, db_session, monkeypatch):
    """POST /tasks/{id}/post-confirm：INSERT 后置 + 异步触发（mock opencode）。"""
    goal, themes, phases, task = _activate_and_get_task(db_session)
    task.status = "已完成"
    db_session.flush()

    monkeypatch.setattr(
        task_app_svc,
        "SessionLocal",
        sessionmaker(bind=db_session.bind, expire_on_commit=False),
    )
    dispatch_calls = []
    with patch.object(
        task_app_svc.OpenCodeClient,
        "dispatch_post_subtasks",
        side_effect=lambda subs: dispatch_calls.append(len(subs)),
    ):
        body = {
            "user_id": "user_001",
            "post_subtasks": [
                {"name": "笔记归档", "type": "后置"},
                {"name": "自测题生成", "type": "后置"},
            ],
        }
        resp = client.post(f"{_API}/tasks/{task.id}/post-confirm", json=body)

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["task_id"] == task.id
    assert data["post_subtask_count"] == 2
    assert data["async_triggered"] is True

    # DB 验证
    subs = db_session.query(Subtask).filter_by(task_id=task.id, type="后置").all()
    assert len(subs) == 2

    # 异步桩被调用
    assert len(dispatch_calls) == 1
    assert dispatch_calls[0] == 2


def test_post_confirm_all_cancelled(client, db_session):
    """post_subtasks 为空 -> 不插入后置，async_triggered=False。"""
    goal, themes, phases, task = _activate_and_get_task(db_session)
    task.status = "已完成"
    db_session.flush()

    body = {"user_id": "user_001", "post_subtasks": []}
    resp = client.post(f"{_API}/tasks/{task.id}/post-confirm", json=body)

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["post_subtask_count"] == 0
    assert data["async_triggered"] is False
    assert db_session.query(Subtask).filter_by(task_id=task.id).count() == 0


def test_post_confirm_non_human_rejects(client, db_session):
    """executor 非 human -> 400。"""
    goal, themes, phases, task = _activate_and_get_task(db_session, executor="agent")
    task.status = "已完成"
    db_session.flush()

    body = {"user_id": "u1", "post_subtasks": [{"name": "x", "type": "后置"}]}
    resp = client.post(f"{_API}/tasks/{task.id}/post-confirm", json=body)
    assert resp.status_code == 400
    assert resp.json()["code"] == 1002


def test_post_confirm_task_not_completed_rejects(client, db_session):
    """task 未完成 -> 400。"""
    goal, themes, phases, task = _activate_and_get_task(db_session)
    # task.status 仍为待执行
    body = {"user_id": "u1", "post_subtasks": [{"name": "x", "type": "后置"}]}
    resp = client.post(f"{_API}/tasks/{task.id}/post-confirm", json=body)
    assert resp.status_code == 400
    assert resp.json()["code"] == 1002


def test_post_confirm_not_found(client, db_session):
    resp = client.post(
        f"{_API}/tasks/no-such-id/post-confirm",
        json={"user_id": "u1", "post_subtasks": []},
    )
    assert resp.status_code == 404


# ===== GET /tasks/{taskId} =====


def test_get_task_detail(client, db_session):
    """GET /tasks/{id}：任务详情含 executor。"""
    goal, themes, phases, task = _activate_and_get_task(db_session)

    resp = client.get(f"{_API}/tasks/{task.id}")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["task_id"] == task.id
    assert data["name"] == task.name
    assert data["status"] == "待执行"
    assert data["executor"] == "human"
    assert data["phase_id"] == phases[0].id


def test_get_task_not_found(client, db_session):
    resp = client.get(f"{_API}/tasks/no-such-id")
    assert resp.status_code == 404
    assert resp.json()["code"] == 1001


# ===== subtask CRUD =====


def test_subtask_crud(client, db_session):
    """POST/GET/PATCH /subtasks 全链路。"""
    goal, themes, phases, task = _activate_and_get_task(db_session)

    # POST create
    resp = client.post(
        f"{_API}/subtasks",
        json={"task_id": task.id, "name": "笔记归档", "type": "后置"},
    )
    assert resp.status_code == 200, resp.text
    sub_id = resp.json()["data"]["subtask_id"]

    # GET
    resp = client.get(f"{_API}/subtasks/{sub_id}")
    assert resp.status_code == 200
    assert resp.json()["data"]["name"] == "笔记归档"

    # PATCH
    resp = client.patch(
        f"{_API}/subtasks/{sub_id}",
        json={"status": "已完成", "output_path": "/out/path"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "已完成"
    assert data["output_path"] == "/out/path"
    assert data["completed_at"] is not None


def test_subtask_create_task_not_found(client, db_session):
    resp = client.post(
        f"{_API}/subtasks",
        json={"task_id": "no-such-id", "name": "x", "type": "前置"},
    )
    assert resp.status_code == 404


def test_subtask_get_not_found(client, db_session):
    resp = client.get(f"{_API}/subtasks/no-such-id")
    assert resp.status_code == 404


# ===== webhook story4B =====


def _post_confirm_payload(message_id, form_value):
    """构造 schema 2.0 form_submit 回调 payload（doc/09 V2）。"""
    return {
        "event": {
            "context": {"open_message_id": message_id},
            "action": {
                "name": "confirm_btn",
                "form_value": form_value,
            },
        }
    }


def test_webhook_post_confirm_inserts(client, db_session, monkeypatch):
    """webhook confirm_btn (post_confirm) -> INSERT 后置 + 异步触发。

    form_value checker: post_<id>=true（勾选=要执行）。
    后置名称从 card_registry context 查（form_value 只给 bool）。
    """
    goal, themes, phases, task = _activate_and_get_task(db_session)
    task.status = "已完成"
    db_session.flush()

    monkeypatch.setattr(
        task_app_svc,
        "SessionLocal",
        sessionmaker(bind=db_session.bind, expire_on_commit=False),
    )
    # mock card_registry 反查 post_confirm 上下文
    post_id = "post-001"
    monkeypatch.setattr(
        "app.webhook.feishu_card.get_card_context",
        lambda msg_id: {
            "type": "post_confirm",
            "task_id": task.id,
            "post_subtasks": [{"id": post_id, "name": "笔记归档"}],
        },
    )
    dispatch_calls = []
    with patch.object(
        task_app_svc.OpenCodeClient,
        "dispatch_post_subtasks",
        side_effect=lambda subs: dispatch_calls.append(len(subs)),
    ):
        payload = _post_confirm_payload("om_test", {f"post_{post_id}": True})
        resp = client.post(_WEBHOOK, json=payload)

    assert resp.status_code == 200, resp.text
    # 方案 B：同步返回 toast + card（已确认后置）
    assert resp.json()["toast"]["content"] == "已确认后置"
    assert len(dispatch_calls) == 1


def test_webhook_no_post_all_cancelled(client, db_session, monkeypatch):
    """webhook confirm_btn (post_confirm) 全不选 -> 全取消，不插入后置。"""
    goal, themes, phases, task = _activate_and_get_task(db_session)
    task.status = "已完成"
    db_session.flush()

    post_id = "post-001"
    monkeypatch.setattr(
        "app.webhook.feishu_card.get_card_context",
        lambda msg_id: {
            "type": "post_confirm",
            "task_id": task.id,
            "post_subtasks": [{"id": post_id, "name": "笔记归档"}],
        },
    )
    # form_value: post_<id>=false（全不选）
    payload = _post_confirm_payload("om_test", {f"post_{post_id}": False})
    resp = client.post(_WEBHOOK, json=payload)

    assert resp.status_code == 200
    # 方案 B：同步返回 toast + card（已确认后置，无后置收尾）
    assert resp.json()["toast"]["content"] == "已确认后置"
    assert db_session.query(Subtask).filter_by(task_id=task.id).count() == 0


def test_webhook_post_confirm_task_not_completed(client, db_session, monkeypatch):
    """webhook confirm_btn (post_confirm) 但 task 未完成 -> 400。"""
    goal, themes, phases, task = _activate_and_get_task(db_session)

    monkeypatch.setattr(
        "app.webhook.feishu_card.get_card_context",
        lambda msg_id: {
            "type": "post_confirm",
            "task_id": task.id,
            "post_subtasks": [],
        },
    )
    payload = _post_confirm_payload("om_test", {})
    resp = client.post(_WEBHOOK, json=payload)
    assert resp.status_code == 400
    assert resp.json()["code"] == 1002
