"""Story6 集成测试：周总结（API + webhook + DB）。

验收要点（doc/01 S6）：
  - GET /weekly/summary/generate 返回统计结构（纯查询，无 LLM）
  - POST /weekly/summary/confirm 置 is_confirmed + 异步 write_weekly_md
  - GET /stats/weekly 周统计
  - webhook story6_已阅周总结 路由 + 3 秒返回不阻塞
  - 周总结不改任何 task/phase 状态（纯回顾）
  - 非法 week 格式 -> 400
"""

from datetime import date
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy.orm import sessionmaker

from app.models.daily_record import DailyRecord
from app.models.daily_task import DailyTask
from app.models.task import Task
from app.models.weekly_record import WeeklyRecord
from app.services import weekly_app_svc
from tests._factory import make_tree

_API = "/api/v1"
_WEBHOOK = "/webhook/feishu/card"
_WEEK = "2026-W27"
_START = date(2026, 6, 29)  # 周一


def _setup_week(db, *, tasks_per_phase=2, completed_count=1):
    """建树 + 激活 + 首日 daily_record + daily_tasks。"""
    goal, themes, phases = make_tree(
        db, n_themes=1, phases_per_theme=1, tasks_per_phase=tasks_per_phase
    )
    goal.status = "进行中"
    themes[0].status = "进行中"
    phases[0].status = "进行中"
    phases[0].activated_at = _START
    db.flush()

    tasks = list(db.query(Task).filter_by(phase_id=phases[0].id).order_by(Task.sort_order))
    for i, t in enumerate(tasks):
        if i < completed_count:
            t.status = "已完成"
    db.flush()

    daily = DailyRecord(
        id=str(uuid4()),
        date=_START,
        week=_WEEK,
        push_source="manual",
        is_confirmed=False,
    )
    db.add(daily)
    db.flush()
    for t in tasks:
        db.add(DailyTask(id=str(uuid4()), daily_id=daily.id, task_id=t.id))
    db.flush()
    return goal, themes, phases, tasks, daily


def _card_value(action_id, **kwargs):
    """构造 schema 2.0 卡片回调 payload（doc/09 V2：event.action.value）。"""
    return {
        "event": {
            "context": {"open_message_id": "om_test"},
            "action": {"value": {"action_id": action_id, **kwargs}},
        }
    }


# ===== GET /weekly/summary/generate =====


def test_weekly_generate_returns_structure(client, db_session):
    """GET /weekly/summary/generate 返回周统计结构。"""
    goal, themes, phases, tasks, daily = _setup_week(
        db_session, tasks_per_phase=2, completed_count=1
    )

    resp = client.get(
        f"{_API}/weekly/summary/generate",
        params={"user_id": "u1", "week": _WEEK},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["week"] == _WEEK
    assert data["date_range"]["start"] == "2026-06-29"
    assert data["date_range"]["end"] == "2026-07-05"
    assert len(data["daily_stats"]) == 7
    first = data["daily_stats"][0]
    assert first["date"] == "2026-06-29"
    assert first["completed_count"] == 1
    assert first["incomplete_count"] == 1
    assert len(data["phase_health"]) == 1
    assert data["phase_health"][0]["completed"] == 1
    assert data["phase_health"][0]["total"] == 2
    assert data["agent_output_stats"]["total_files"] == 0
    # supervisor_linking_status 占位 None
    assert data["supervisor_linking_status"]["next_phase"] is None
    assert data["supervisor_linking_status"]["suggested_deadline"] is None


def test_weekly_generate_invalid_week_400(client, db_session):
    """非法 week 格式 -> 400。"""
    resp = client.get(
        f"{_API}/weekly/summary/generate",
        params={"user_id": "u1", "week": "bad-week"},
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == 1002


# ===== POST /weekly/summary/confirm =====


def test_weekly_confirm_inserts_and_async_write(client, db_session, monkeypatch):
    """POST /weekly/summary/confirm 置 is_confirmed + 异步 write_weekly_md。"""
    goal, themes, phases, tasks, daily = _setup_week(
        db_session, tasks_per_phase=1, completed_count=0
    )

    monkeypatch.setattr(
        weekly_app_svc,
        "SessionLocal",
        sessionmaker(bind=db_session.bind, expire_on_commit=False),
    )
    write_calls = []
    with patch.object(
        weekly_app_svc,
        "write_weekly_md",
        side_effect=lambda *a, **kw: write_calls.append(a),
    ):
        resp = client.post(f"{_API}/weekly/summary/confirm", json={"week": _WEEK})

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["week"] == _WEEK
    assert data["confirmed"] is True

    db_session.flush()
    rec = db_session.query(WeeklyRecord).filter_by(week=_WEEK).one()
    assert rec.is_confirmed is True
    assert rec.confirmed_at is not None
    assert rec.date_range_start == _START
    assert len(write_calls) == 1


def test_weekly_confirm_updates_existing_record(client, db_session, monkeypatch):
    """已存在未确认的 weekly_record -> UPDATE（不重复 INSERT）。"""
    goal, themes, phases, tasks, daily = _setup_week(
        db_session, tasks_per_phase=1, completed_count=0
    )
    # 预先建未确认的 weekly_record
    db_session.add(
        WeeklyRecord(
            id=str(uuid4()),
            week=_WEEK,
            date_range_start=_START,
            date_range_end=date(2026, 7, 5),
            is_confirmed=False,
        )
    )
    db_session.flush()

    monkeypatch.setattr(
        weekly_app_svc,
        "SessionLocal",
        sessionmaker(bind=db_session.bind, expire_on_commit=False),
    )
    with patch.object(weekly_app_svc, "write_weekly_md"):
        resp = client.post(f"{_API}/weekly/summary/confirm", json={"week": _WEEK})

    assert resp.status_code == 200, resp.text
    db_session.flush()
    recs = db_session.query(WeeklyRecord).filter_by(week=_WEEK).all()
    assert len(recs) == 1  # 未重复 INSERT
    assert recs[0].is_confirmed is True


def test_weekly_confirm_duplicate_returns_409(client, db_session, monkeypatch):
    """重复确认 -> 409。"""
    goal, themes, phases, tasks, daily = _setup_week(
        db_session, tasks_per_phase=1, completed_count=0
    )
    monkeypatch.setattr(
        weekly_app_svc,
        "SessionLocal",
        sessionmaker(bind=db_session.bind, expire_on_commit=False),
    )
    with patch.object(weekly_app_svc, "write_weekly_md"):
        resp1 = client.post(f"{_API}/weekly/summary/confirm", json={"week": _WEEK})
        assert resp1.status_code == 200

        resp2 = client.post(f"{_API}/weekly/summary/confirm", json={"week": _WEEK})
    assert resp2.status_code == 409
    assert resp2.json()["code"] == 1003


def test_weekly_confirm_does_not_change_task_phase_status(client, db_session, monkeypatch):
    """周总结纯回顾：confirm 不改任何 task/phase 状态。"""
    goal, themes, phases, tasks, daily = _setup_week(
        db_session, tasks_per_phase=2, completed_count=1
    )
    # 记录 confirm 前状态
    task_statuses_before = [t.status for t in tasks]
    phase_status_before = phases[0].status

    monkeypatch.setattr(
        weekly_app_svc,
        "SessionLocal",
        sessionmaker(bind=db_session.bind, expire_on_commit=False),
    )
    with patch.object(weekly_app_svc, "write_weekly_md"):
        resp = client.post(f"{_API}/weekly/summary/confirm", json={"week": _WEEK})

    assert resp.status_code == 200, resp.text
    db_session.flush()
    # task/phase 状态未变
    tasks_after = list(
        db_session.query(Task).filter_by(phase_id=phases[0].id).order_by(Task.sort_order)
    )
    assert [t.status for t in tasks_after] == task_statuses_before
    assert db_session.refresh(phases[0]) is None
    assert phases[0].status == phase_status_before


# ===== GET /stats/weekly =====


def test_stats_weekly_returns_data(client, db_session):
    """GET /stats/weekly 返回周统计数据。"""
    goal, themes, phases, tasks, daily = _setup_week(
        db_session, tasks_per_phase=2, completed_count=1
    )

    resp = client.get(
        f"{_API}/stats/weekly",
        params={"user_id": "u1", "week": _WEEK},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["week"] == _WEEK
    assert len(data["daily_stats"]) == 7
    assert len(data["phase_health"]) == 1
    assert data["supervisor_linking_status"]["next_phase"] is None


# ===== webhook story6_已阅周总结 =====


def test_webhook_story6_confirm(client, db_session, monkeypatch):
    """webhook story6_已阅周总结 -> 置 is_confirmed + 异步写 weekly.md。"""
    goal, themes, phases, tasks, daily = _setup_week(
        db_session, tasks_per_phase=1, completed_count=0
    )

    monkeypatch.setattr(
        weekly_app_svc,
        "SessionLocal",
        sessionmaker(bind=db_session.bind, expire_on_commit=False),
    )
    with patch.object(weekly_app_svc, "write_weekly_md"):
        payload = _card_value("story6_已阅周总结", week=_WEEK, user_id="u1")
        resp = client.post(_WEBHOOK, json=payload)

    assert resp.status_code == 200, resp.text
    # 方案 B：同步返回 toast + card（已阅态）
    assert resp.json()["toast"]["content"] == "已阅"

    db_session.flush()
    rec = db_session.query(WeeklyRecord).filter_by(week=_WEEK).one()
    assert rec.is_confirmed is True


def test_webhook_story6_missing_week(client, db_session):
    """webhook story6_已阅周总结 缺 week -> 400（1002）。"""
    payload = _card_value("story6_已阅周总结")
    resp = client.post(_WEBHOOK, json=payload)
    assert resp.status_code == 200
    assert resp.json()["code"] == 1002
