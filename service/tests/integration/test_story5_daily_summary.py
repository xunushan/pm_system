"""Story5 集成测试：日终总结 + 异议 PATCH + webhook（API + DB）。

验收要点（doc/01 S5）：
  - GET /daily/summary/generate 返回统计结构（纯查询，无 LLM）
  - POST /daily/summary/confirm 置 is_confirmed + 异步 write_daily_md
  - PATCH /tasks/{id} 双向（forward 完成级联 / revert 回退级联 + 系统 reason 审计）
  - webhook story5_三动作 路由 + 3 秒返回不阻塞
  - GET /stats/daily 统计查询
"""

from datetime import date, timedelta
from unittest.mock import patch

from sqlalchemy.orm import sessionmaker

from app.models.daily_record import DailyRecord
from app.models.daily_task import DailyTask
from app.models.status_change_log import StatusChangeLog
from app.models.task import Task
from app.services import daily_app_svc
from tests._factory import make_tree

_API = "/api/v1"
_WEBHOOK = "/webhook/feishu/card"
_TODAY = date(2026, 7, 6)


def _iso_week(d: date) -> str:
    iso = d.isocalendar()
    return f"{iso[0]}-W{iso[1]}"


def _setup_daily_with_tasks(db_session, *, tasks_per_phase=2, completed_count=0):
    """建树 + 激活 + 创建 daily_record + daily_tasks，返回 (goal, themes, phases, tasks, daily)。"""
    goal, themes, phases = make_tree(
        db_session, n_themes=1, phases_per_theme=1, tasks_per_phase=tasks_per_phase
    )
    goal.status = "进行中"
    themes[0].status = "进行中"
    phases[0].status = "进行中"
    phases[0].activated_at = _TODAY - timedelta(days=1)
    db_session.flush()

    tasks = list(
        db_session.query(Task).filter(Task.phase_id == phases[0].id).order_by(Task.sort_order)
    )
    # 标记部分完成
    for i, t in enumerate(tasks):
        if i < completed_count:
            t.status = "已完成"
    db_session.flush()

    # 创建 daily_record + daily_tasks
    from uuid import uuid4

    daily = DailyRecord(
        id=str(uuid4()),
        date=_TODAY,
        week=_iso_week(_TODAY),
        push_source="manual",
        is_confirmed=False,
    )
    db_session.add(daily)
    db_session.flush()
    for t in tasks:
        dt = DailyTask(id=str(uuid4()), daily_id=daily.id, task_id=t.id)
        db_session.add(dt)
    db_session.flush()

    return goal, themes, phases, tasks, daily


# ===== GET /daily/summary/generate =====


def test_summary_generate_returns_structure(client, db_session):
    """GET /daily/summary/generate 返回统计结构。"""
    goal, themes, phases, tasks, daily = _setup_daily_with_tasks(
        db_session, tasks_per_phase=2, completed_count=1
    )

    resp = client.get(
        f"{_API}/daily/summary/generate",
        params={"user_id": "u1", "date": "2026-07-06"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["date"] == "2026-07-06"
    assert data["daily_id"] == daily.id
    assert data["is_confirmed"] is False
    assert len(data["completed_tasks"]) == 1
    assert len(data["incomplete_tasks"]) == 1
    assert data["completed_tasks"][0]["task_id"] == tasks[0].id
    assert data["incomplete_tasks"][0]["task_id"] == tasks[1].id
    assert len(data["phase_health"]) == 1
    ph = data["phase_health"][0]
    assert ph["completed"] == 1
    assert ph["total"] == 2
    assert ph["status"] == "进行中"
    assert data["global_active_limit"] == 3


def test_summary_generate_no_daily_record(client, db_session):
    """无当日 daily_record -> daily_id=None, is_confirmed=False。"""
    resp = client.get(
        f"{_API}/daily/summary/generate",
        params={"user_id": "u1", "date": "2026-07-06"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["daily_id"] is None
    assert data["is_confirmed"] is False
    assert data["completed_tasks"] == []
    assert data["incomplete_tasks"] == []


# ===== POST /daily/summary/confirm =====


def test_summary_confirm_sets_is_confirmed(client, db_session, monkeypatch):
    """POST /daily/summary/confirm 置 is_confirmed + 异步 write_daily_md。"""
    goal, themes, phases, tasks, daily = _setup_daily_with_tasks(
        db_session, tasks_per_phase=1, completed_count=1
    )

    monkeypatch.setattr(
        daily_app_svc,
        "SessionLocal",
        sessionmaker(bind=db_session.bind, expire_on_commit=False),
    )
    write_calls = []
    with patch.object(
        daily_app_svc,
        "write_daily_md",
        side_effect=lambda *a, **kw: write_calls.append(a),
    ):
        resp = client.post(
            f"{_API}/daily/summary/confirm",
            json={"daily_id": daily.id},
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["daily_id"] == daily.id
    assert data["confirmed"] is True

    db_session.flush()
    updated = db_session.get(DailyRecord, daily.id)
    assert updated.is_confirmed is True
    assert updated.confirmed_at is not None
    assert len(write_calls) == 1


def test_summary_confirm_not_found(client, db_session):
    """不存在的 daily_id -> 404。"""
    resp = client.post(
        f"{_API}/daily/summary/confirm",
        json={"daily_id": "no-such-id"},
    )
    assert resp.status_code == 404
    assert resp.json()["code"] == 1001


def test_summary_confirm_already_confirmed(client, db_session):
    """重复确认 -> 409。"""
    goal, themes, phases, tasks, daily = _setup_daily_with_tasks(
        db_session, tasks_per_phase=1, completed_count=0
    )
    daily.is_confirmed = True
    db_session.flush()

    resp = client.post(
        f"{_API}/daily/summary/confirm",
        json={"daily_id": daily.id},
    )
    assert resp.status_code == 409
    assert resp.json()["code"] == 1003


# ===== PATCH /tasks/{id}（日终异议双向）=====


def test_patch_forward_marks_complete(client, db_session):
    """PATCH /tasks/{id} forward：待执行->已完成 + 完成级联。"""
    goal, themes, phases, tasks, daily = _setup_daily_with_tasks(
        db_session, tasks_per_phase=1, completed_count=0
    )

    resp = client.patch(
        f"{_API}/tasks/{tasks[0].id}",
        json={"status": "已完成", "triggered_by": "user"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["task_id"] == tasks[0].id
    assert data["status"] == "已完成"
    assert data["cascade"]["phase_completed"] is True
    assert data["cascade"]["theme_completed"] is True
    assert data["cascade"]["goal_completed"] is True

    db_session.flush()
    assert tasks[0].status == "已完成"
    assert tasks[0].completed_at is not None
    assert phases[0].status == "已完成"
    assert goal.status == "已完成"

    # 审计：1 forward(task)
    forward_logs = (
        db_session.query(StatusChangeLog).filter(StatusChangeLog.change_type == "forward").all()
    )
    assert len(forward_logs) == 1
    assert forward_logs[0].triggered_by == "user"


def test_patch_revert_marks_incomplete(client, db_session):
    """PATCH /tasks/{id} revert：已完成->待执行 + 回退级联 + 系统 reason 审计。"""
    goal, themes, phases, tasks, daily = _setup_daily_with_tasks(
        db_session, tasks_per_phase=1, completed_count=1
    )
    # 先完成级联（phase/theme/goal 完成）
    from app.core import cascade

    cascade.cascade_status(db_session, "task", tasks[0].id)
    db_session.flush()
    assert phases[0].status == "已完成"
    assert goal.status == "已完成"

    # revert
    resp = client.patch(
        f"{_API}/tasks/{tasks[0].id}",
        json={"status": "待执行", "triggered_by": "user"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["task_id"] == tasks[0].id
    assert data["status"] == "待执行"
    assert data["cascade"]["phase_reverted"] is True
    assert data["cascade"]["theme_reverted"] is True
    assert data["cascade"]["goal_reverted"] is True

    db_session.flush()
    assert tasks[0].status == "待执行"
    assert tasks[0].completed_at is None
    assert phases[0].status == "进行中"
    assert phases[0].completed_at is None
    assert goal.status == "进行中"

    # 审计：1 revert(task)，reason="日终异议-标记未完成"
    revert_logs = (
        db_session.query(StatusChangeLog).filter(StatusChangeLog.change_type == "revert").all()
    )
    assert len(revert_logs) == 1
    assert revert_logs[0].reason == "日终异议-标记未完成"
    assert revert_logs[0].triggered_by == "user"
    assert revert_logs[0].from_status == "已完成"
    assert revert_logs[0].to_status == "待执行"


def test_patch_forward_already_completed_409(client, db_session):
    """forward 时 task 已完成 -> 409。"""
    goal, themes, phases, tasks, daily = _setup_daily_with_tasks(
        db_session, tasks_per_phase=1, completed_count=1
    )
    tasks[0].status = "已完成"
    db_session.flush()

    resp = client.patch(
        f"{_API}/tasks/{tasks[0].id}",
        json={"status": "已完成"},
    )
    assert resp.status_code == 409
    assert resp.json()["code"] == 1003


def test_patch_not_found(client, db_session):
    """不存在的 task_id -> 404。"""
    resp = client.patch(
        f"{_API}/tasks/no-such-id",
        json={"status": "已完成"},
    )
    assert resp.status_code == 404
    assert resp.json()["code"] == 1001


def test_patch_invalid_status_400(client, db_session):
    """不支持的目标状态 -> 400。"""
    goal, themes, phases, tasks, daily = _setup_daily_with_tasks(
        db_session, tasks_per_phase=1, completed_count=0
    )

    resp = client.patch(
        f"{_API}/tasks/{tasks[0].id}",
        json={"status": "已暂停"},
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == 1002


def test_patch_forward_paused_rejects(client, db_session):
    """已暂停任务 forward -> 400（暂停态不通过异议直接完成）。"""
    goal, themes, phases, tasks, daily = _setup_daily_with_tasks(
        db_session, tasks_per_phase=1, completed_count=0
    )
    tasks[0].status = "已暂停"
    db_session.flush()

    resp = client.patch(
        f"{_API}/tasks/{tasks[0].id}",
        json={"status": "已完成"},
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == 1002


def test_patch_revert_paused_rejects(client, db_session):
    """已暂停任务 revert -> 400（暂停态不通过异议论退）。"""
    goal, themes, phases, tasks, daily = _setup_daily_with_tasks(
        db_session, tasks_per_phase=1, completed_count=0
    )
    tasks[0].status = "已暂停"
    db_session.flush()

    resp = client.patch(
        f"{_API}/tasks/{tasks[0].id}",
        json={"status": "待执行"},
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == 1002


# ===== GET /stats/daily =====


def test_stats_daily_returns_data(client, db_session):
    """GET /stats/daily 返回日统计数据。"""
    goal, themes, phases, tasks, daily = _setup_daily_with_tasks(
        db_session, tasks_per_phase=2, completed_count=1
    )

    resp = client.get(
        f"{_API}/stats/daily",
        params={"user_id": "u1", "date": "2026-07-06"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["date"] == "2026-07-06"
    assert data["daily_id"] == daily.id
    assert data["is_confirmed"] is False
    assert len(data["completed_tasks"]) == 1
    assert len(data["incomplete_tasks"]) == 1
    assert len(data["phase_health"]) == 1
    assert data["phase_health"][0]["completed"] == 1
    assert data["phase_health"][0]["total"] == 2
    assert data["global_active_limit"] == 3


# ===== webhook story5_三动作 =====


def _card_value(action_id, message_id="om_test", **kwargs):
    """构造 schema 2.0 卡片回调 payload（doc/09 V2）。"""
    return {
        "event": {
            "context": {"open_message_id": message_id},
            "action": {"value": {"action_id": action_id, **kwargs}},
        }
    }


def _daily_summary_payload(message_id, form_value):
    """构造 schema 2.0 form_submit 回调 payload（confirm_btn, daily_summary）。"""
    return {
        "event": {
            "context": {"open_message_id": message_id},
            "action": {
                "name": "confirm_btn",
                "form_value": form_value,
            },
        }
    }


def test_webhook_story5_mark_complete(client, db_session, monkeypatch):
    """webhook confirm_btn (daily_summary) 勾选未完成任务 -> PATCH forward。

    doc/09 §S5：checker 勾选=已完成，对比初始 checked 状态反转变化的任务。
    初始状态 = DB task.status（card 从 DB 构建）。未完成 -> 勾选 -> forward。
    """
    goal, themes, phases, tasks, daily = _setup_daily_with_tasks(
        db_session, tasks_per_phase=1, completed_count=0
    )

    monkeypatch.setattr(
        daily_app_svc,
        "SessionLocal",
        sessionmaker(bind=db_session.bind, expire_on_commit=False),
    )
    monkeypatch.setattr(
        "app.webhook.feishu_card.get_card_context",
        lambda msg_id: {"type": "daily_summary", "daily_id": daily.id},
    )
    with patch.object(daily_app_svc, "write_daily_md"):
        payload = _daily_summary_payload("msg_001", {f"task_{tasks[0].id}": True})
        resp = client.post(_WEBHOOK, json=payload)

    assert resp.status_code == 200, resp.text
    assert resp.json()["toast"]["content"] == "日终总结已确认"

    db_session.flush()
    assert tasks[0].status == "已完成"
    assert daily.is_confirmed is True


def test_webhook_story5_mark_incomplete(client, db_session, monkeypatch):
    """webhook confirm_btn (daily_summary) 取消已完成任务 -> PATCH revert。

    初始状态 = DB task.status（已完成 -> checked）。取消勾选 -> revert。
    """
    goal, themes, phases, tasks, daily = _setup_daily_with_tasks(
        db_session, tasks_per_phase=1, completed_count=1
    )
    # 先完成级联
    from app.core import cascade

    cascade.cascade_status(db_session, "task", tasks[0].id)
    db_session.flush()

    monkeypatch.setattr(
        daily_app_svc,
        "SessionLocal",
        sessionmaker(bind=db_session.bind, expire_on_commit=False),
    )
    monkeypatch.setattr(
        "app.webhook.feishu_card.get_card_context",
        lambda msg_id: {"type": "daily_summary", "daily_id": daily.id},
    )
    with patch.object(daily_app_svc, "write_daily_md"):
        payload = _daily_summary_payload("msg_001", {f"task_{tasks[0].id}": False})
        resp = client.post(_WEBHOOK, json=payload)

    assert resp.status_code == 200, resp.text
    assert resp.json()["toast"]["content"] == "日终总结已确认"

    db_session.flush()
    assert tasks[0].status == "待执行"
    assert phases[0].status == "进行中"
    assert daily.is_confirmed is True


def test_webhook_story5_no_change_no_patch(client, db_session, monkeypatch):
    """webhook confirm_btn (daily_summary) 勾选状态与 DB 一致 -> 不调 patch_status。"""
    goal, themes, phases, tasks, daily = _setup_daily_with_tasks(
        db_session, tasks_per_phase=1, completed_count=1
    )
    db_session.flush()

    monkeypatch.setattr(
        daily_app_svc,
        "SessionLocal",
        sessionmaker(bind=db_session.bind, expire_on_commit=False),
    )
    monkeypatch.setattr(
        "app.webhook.feishu_card.get_card_context",
        lambda msg_id: {"type": "daily_summary", "daily_id": daily.id},
    )
    with patch.object(daily_app_svc, "write_daily_md"):
        # 已完成任务勾选 true = 状态一致，不调 patch_status
        payload = _daily_summary_payload("msg_001", {f"task_{tasks[0].id}": True})
        resp = client.post(_WEBHOOK, json=payload)

    assert resp.status_code == 200, resp.text
    assert resp.json()["toast"]["content"] == "日终总结已确认"
    assert daily.is_confirmed is True


def test_webhook_story5_confirm_summary(client, db_session, monkeypatch):
    """webhook confirm_btn (daily_summary) -> 置 is_confirmed + 异步写 daily.md。"""
    goal, themes, phases, tasks, daily = _setup_daily_with_tasks(
        db_session, tasks_per_phase=1, completed_count=0
    )

    monkeypatch.setattr(
        daily_app_svc,
        "SessionLocal",
        sessionmaker(bind=db_session.bind, expire_on_commit=False),
    )
    monkeypatch.setattr(
        "app.webhook.feishu_card.get_card_context",
        lambda msg_id: {"type": "daily_summary", "daily_id": daily.id},
    )
    with patch.object(daily_app_svc, "write_daily_md"):
        payload = _daily_summary_payload("om_test", {f"task_{tasks[0].id}": False})
        resp = client.post(_WEBHOOK, json=payload)

    assert resp.status_code == 200, resp.text
    assert resp.json()["toast"]["content"] == "日终总结已确认"

    db_session.flush()
    assert daily.is_confirmed is True


def test_webhook_story5_no_card_context(client, db_session, monkeypatch):
    """card_registry 反查 None -> 1002（容错，不崩）。"""
    monkeypatch.setattr(
        "app.webhook.feishu_card.get_card_context",
        lambda msg_id: None,
    )
    payload = _daily_summary_payload("om_test", {})
    resp = client.post(_WEBHOOK, json=payload)
    assert resp.status_code == 200
    assert resp.json()["code"] == 1002
