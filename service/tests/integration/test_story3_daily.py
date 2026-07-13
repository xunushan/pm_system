"""Story3 集成测试：daily pool + confirm 全链路（API + DB）+ webhook 回调。

验收要点（doc/01 S3）：
  - pool 过滤已激活阶段 + 排除已暂停
  - pool 返回 theme_type 供 pm-daily LLM 推断 executor
  - confirm 事务 INSERT daily_records/daily_tasks/subtasks
  - 重复确认 -> 409
  - task 不存在/未激活/已暂停 -> 拒绝
  - webhook story3 确认回调
"""

from datetime import date, timedelta
from unittest.mock import patch

from sqlalchemy.orm import sessionmaker

from app.models.daily_record import DailyRecord
from app.models.daily_task import DailyTask
from app.models.subtask import Subtask
from app.services import daily_app_svc
from tests._factory import make_tree

_API = "/api/v1"
_WEBHOOK = "/webhook/feishu/card"
_TODAY = date(2026, 7, 6)
_YESTERDAY = _TODAY - timedelta(days=1)


def _activate(phase, *, deadline=date(2026, 7, 15)):
    phase.status = "进行中"
    phase.activated_at = _YESTERDAY
    phase.deadline = deadline


def _pool_params(user_id="u1", date=None):
    params = {"user_id": user_id}
    if date:
        params["date"] = date
    return params


# ===== GET /daily/plans/pool =====


def test_get_pool_full_response(client, db_session):
    """GET /daily/plans/pool 完整响应结构。"""
    goal, themes, phases = make_tree(db_session, n_themes=1, phases_per_theme=1, tasks_per_phase=3)
    _activate(phases[0])
    db_session.flush()

    resp = client.get(f"{_API}/daily/plans/pool", params=_pool_params(date="2026-07-06"))
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["date"] == "2026-07-06"
    assert len(data["active_phases"]) == 1
    ap = data["active_phases"][0]
    assert ap["phase_id"] == phases[0].id
    assert ap["theme_name"] == themes[0].name
    assert ap["theme_type"] == "learning"
    assert ap["progress"] == "0/3"
    assert ap["remaining_tasks"] == 3
    assert len(data["pending_tasks"]) == 3
    assert data["global_active_count"] == 1
    assert data["global_active_limit"] == 3


def test_get_pool_empty_when_no_active(client, db_session):
    """无已激活阶段 -> pool 空。"""
    make_tree(db_session, n_themes=1, phases_per_theme=1, tasks_per_phase=2)
    db_session.flush()

    resp = client.get(f"{_API}/daily/plans/pool", params=_pool_params(date="2026-07-06"))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["active_phases"] == []
    assert data["pending_tasks"] == []


def test_get_pool_excludes_paused(client, db_session):
    """已暂停阶段不出现在 pool。"""
    goal, themes, phases = make_tree(db_session, n_themes=2, phases_per_theme=1, tasks_per_phase=1)
    _activate(phases[0])
    phases[1].status = "已暂停"
    phases[1].activated_at = _YESTERDAY
    db_session.flush()

    resp = client.get(f"{_API}/daily/plans/pool", params=_pool_params(date="2026-07-06"))
    data = resp.json()["data"]
    assert len(data["active_phases"]) == 1


# ===== POST /daily/confirm =====


def test_confirm_full_flow(client, db_session, monkeypatch):
    """POST /daily/confirm 完整事务 + 异步触发（mock opencode）。"""
    goal, themes, phases = make_tree(db_session, n_themes=1, phases_per_theme=1, tasks_per_phase=2)
    _activate(phases[0])
    from app.models.task import Task

    tasks = db_session.query(Task).filter_by(phase_id=phases[0].id).all()
    db_session.flush()

    # monkeypatch SessionLocal -> 测试 engine
    monkeypatch.setattr(
        daily_app_svc,
        "SessionLocal",
        sessionmaker(bind=db_session.bind, expire_on_commit=False),
    )
    dispatch_calls = []
    with patch.object(
        daily_app_svc.OpenCodeClient,
        "dispatch_pre_subtasks",
        side_effect=lambda subs: dispatch_calls.append(len(subs)),
    ):
        body = {
            "user_id": "u1",
            "date": "2026-07-06",
            "task_ids": [tasks[0].id, tasks[1].id],
            "pre_subtasks": [
                {"name": "搜集资料", "type": "前置"},
                {"name": "准备环境", "type": "前置"},
            ],
        }
        resp = client.post(f"{_API}/daily/confirm", json=body)

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["task_count"] == 2
    assert data["pre_subtask_count"] == 2
    assert data["async_triggered"] is True

    # DB 验证
    assert db_session.query(DailyRecord).count() == 1
    assert db_session.query(DailyTask).count() == 2
    assert db_session.query(Subtask).count() == 2

    # 异步桩被调用
    assert len(dispatch_calls) == 1


def test_confirm_duplicate_returns_409(client, db_session):
    """重复确认同日 -> 409（1003）。"""
    goal, themes, phases = make_tree(db_session, n_themes=1, phases_per_theme=1, tasks_per_phase=1)
    _activate(phases[0])
    from app.models.task import Task

    task = db_session.query(Task).filter_by(phase_id=phases[0].id).one()
    db_session.flush()

    body = {"user_id": "u1", "date": "2026-07-06", "task_ids": [task.id]}
    resp1 = client.post(f"{_API}/daily/confirm", json=body)
    assert resp1.status_code == 200

    resp2 = client.post(f"{_API}/daily/confirm", json=body)
    assert resp2.status_code == 409
    assert resp2.json()["code"] == 1003


def test_confirm_task_not_found_returns_404(client, db_session):
    """task 不存在 -> 404。"""
    goal, themes, phases = make_tree(db_session, n_themes=1, phases_per_theme=1, tasks_per_phase=1)
    _activate(phases[0])
    db_session.flush()

    body = {"user_id": "u1", "date": "2026-07-06", "task_ids": ["no-such-task"]}
    resp = client.post(f"{_API}/daily/confirm", json=body)
    assert resp.status_code == 404
    assert resp.json()["code"] == 1001


def test_confirm_task_not_activated_returns_400(client, db_session):
    """task 所属阶段未激活 -> 400。"""
    goal, themes, phases = make_tree(db_session, n_themes=1, phases_per_theme=1, tasks_per_phase=1)
    from app.models.task import Task

    task = db_session.query(Task).filter_by(phase_id=phases[0].id).one()
    db_session.flush()

    body = {"user_id": "u1", "date": "2026-07-06", "task_ids": [task.id]}
    resp = client.post(f"{_API}/daily/confirm", json=body)
    assert resp.status_code == 400
    assert resp.json()["code"] == 1002


def test_confirm_task_paused_phase_returns_400(client, db_session):
    """task 所属阶段已暂停 -> 400。"""
    goal, themes, phases = make_tree(db_session, n_themes=1, phases_per_theme=1, tasks_per_phase=1)
    phases[0].status = "已暂停"
    phases[0].activated_at = _YESTERDAY
    from app.models.task import Task

    task = db_session.query(Task).filter_by(phase_id=phases[0].id).one()
    db_session.flush()

    body = {"user_id": "u1", "date": "2026-07-06", "task_ids": [task.id]}
    resp = client.post(f"{_API}/daily/confirm", json=body)
    assert resp.status_code == 400


def test_confirm_no_pre_subtasks(client, db_session):
    """无前置 -> pre_subtask_count=0，async_triggered=false（learning 无 agent）。"""
    goal, themes, phases = make_tree(db_session, n_themes=1, phases_per_theme=1, tasks_per_phase=1)
    _activate(phases[0])
    from app.models.task import Task

    task = db_session.query(Task).filter_by(phase_id=phases[0].id).one()
    db_session.flush()

    body = {"user_id": "u1", "date": "2026-07-06", "task_ids": [task.id], "pre_subtasks": []}
    resp = client.post(f"{_API}/daily/confirm", json=body)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["pre_subtask_count"] == 0
    assert data["async_triggered"] is False


# ===== 回归 #12 #13 =====


def test_confirm_then_summary_confirm_succeeds(client, db_session, monkeypatch):
    """S3 confirm 后 S5 summary/confirm 能成功（200），回归 #12。

    S3 不应误设 is_confirmed=True（否则 S5 永远 409）。
    """
    goal, themes, phases = make_tree(db_session, n_themes=1, phases_per_theme=1, tasks_per_phase=1)
    _activate(phases[0])
    from app.models.task import Task

    task = db_session.query(Task).filter_by(phase_id=phases[0].id).one()
    db_session.flush()

    monkeypatch.setattr(
        daily_app_svc,
        "SessionLocal",
        sessionmaker(bind=db_session.bind, expire_on_commit=False),
    )

    # S3: POST /daily/confirm
    body = {"user_id": "u1", "date": "2026-07-06", "task_ids": [task.id]}
    resp1 = client.post(f"{_API}/daily/confirm", json=body)
    assert resp1.status_code == 200, resp1.text
    daily_id = resp1.json()["data"]["daily_id"]

    # S3 后 is_confirmed=False
    dr = db_session.query(DailyRecord).one()
    assert dr.is_confirmed is False

    # S5: POST /daily/summary/confirm -> 200（不 409）
    with patch.object(daily_app_svc, "write_daily_md"):
        resp2 = client.post(
            f"{_API}/daily/summary/confirm",
            json={"daily_id": daily_id},
        )
    assert resp2.status_code == 200, resp2.text
    assert resp2.json()["data"]["confirmed"] is True

    # S5 后 is_confirmed=True
    db_session.flush()
    assert dr.is_confirmed is True


def test_confirm_invalid_push_source_returns_422(client, db_session):
    """非法 push_source -> 422（pydantic Literal 校验），回归 #13。"""
    goal, themes, phases = make_tree(db_session, n_themes=1, phases_per_theme=1, tasks_per_phase=1)
    _activate(phases[0])
    from app.models.task import Task

    task = db_session.query(Task).filter_by(phase_id=phases[0].id).one()
    db_session.flush()

    body = {
        "user_id": "u1",
        "date": "2026-07-06",
        "task_ids": [task.id],
        "push_source": "card",  # 非法值
    }
    resp = client.post(f"{_API}/daily/confirm", json=body)
    assert resp.status_code == 422
    # 确保没有写入 DB
    assert db_session.query(DailyRecord).count() == 0


def test_webhook_story3_invalid_push_source_returns_1002(client, db_session, monkeypatch):
    """webhook story3 非法 push_source -> 422 pydantic 校验，回归 #13。

    schema 2.0 下 push_source 在 webhook 硬编码为 "manual"，
    此测试改为通过 API 直传非法 push_source 验证 pydantic 校验仍生效。
    """
    goal, themes, phases = make_tree(db_session, n_themes=1, phases_per_theme=1, tasks_per_phase=1)
    _activate(phases[0])
    from app.models.task import Task

    task = db_session.query(Task).filter_by(phase_id=phases[0].id).one()
    db_session.flush()

    body = {
        "user_id": "u1",
        "date": "2026-07-06",
        "task_ids": [task.id],
        "pre_subtasks": [],
        "push_source": "card",  # 非法值
    }
    resp = client.post(f"{_API}/daily/confirm", json=body)
    assert resp.status_code == 422
    assert db_session.query(DailyRecord).count() == 0


# ===== webhook =====


def _daily_plan_payload(message_id, form_value):
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


def test_webhook_story3_confirm(client, db_session, monkeypatch):
    """webhook confirm_btn (daily_plan) -> 确认事务。

    form_value checker: task_<id>=true（勾选今日要做）+ pre_<id>=true（勾选前置）。
    前置名称从 card_registry context 查（form_value 只给 bool）。
    """
    goal, themes, phases = make_tree(db_session, n_themes=1, phases_per_theme=1, tasks_per_phase=1)
    _activate(phases[0])
    from app.models.task import Task

    task = db_session.query(Task).filter_by(phase_id=phases[0].id).one()
    db_session.flush()

    monkeypatch.setattr(
        daily_app_svc,
        "SessionLocal",
        sessionmaker(bind=db_session.bind, expire_on_commit=False),
    )
    # mock card_registry 反查 daily_plan 上下文
    pre_id = "pre-001"
    monkeypatch.setattr(
        "app.webhook.feishu_card.get_card_context",
        lambda msg_id: {
            "type": "daily_plan",
            "date": "2026-07-06",
            "prerequisites": [{"id": pre_id, "name": "准备环境"}],
        },
    )

    payload = _daily_plan_payload(
        "om_test",
        {f"task_{task.id}": True, f"pre_{pre_id}": True},
    )
    resp = client.post(_WEBHOOK, json=payload)
    assert resp.status_code == 200, resp.text
    # 方案 B：同步返回 toast + card
    assert resp.json()["toast"]["content"] == "今日计划已确认"

    # DB 验证
    assert db_session.query(DailyRecord).count() == 1
    assert db_session.query(DailyTask).count() == 1
    assert db_session.query(Subtask).count() == 1


def test_webhook_story3_confirm_duplicate_409(client, db_session, monkeypatch):
    """webhook 重复确认同日 -> 409。"""
    goal, themes, phases = make_tree(db_session, n_themes=1, phases_per_theme=1, tasks_per_phase=1)
    _activate(phases[0])
    from app.models.task import Task

    task = db_session.query(Task).filter_by(phase_id=phases[0].id).one()
    db_session.flush()

    monkeypatch.setattr(
        daily_app_svc,
        "SessionLocal",
        sessionmaker(bind=db_session.bind, expire_on_commit=False),
    )
    monkeypatch.setattr(
        "app.webhook.feishu_card.get_card_context",
        lambda msg_id: {"type": "daily_plan", "date": "2026-07-06", "prerequisites": []},
    )

    payload = _daily_plan_payload("om_test", {f"task_{task.id}": True})
    resp1 = client.post(_WEBHOOK, json=payload)
    assert resp1.status_code == 200

    resp2 = client.post(_WEBHOOK, json=payload)
    assert resp2.status_code == 409
    assert resp2.json()["code"] == 1003


def test_webhook_unknown_action_still_noop(client):
    """未知 action_id -> noop（S2 测试已覆盖，确保不影响）。"""
    payload = {"event": {"context": {}, "action": {"value": {"action_id": "unknown.x"}}}}
    resp = client.post(_WEBHOOK, json=payload)
    assert resp.status_code == 200
    assert resp.json()["code"] == 0
