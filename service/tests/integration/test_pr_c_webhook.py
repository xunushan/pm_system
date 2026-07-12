"""PR-C webhook 双路由 + story1/story2 handler 集成测试。

schema 2.0 回调结构（doc/09 V2）：
  - form 外按钮：event.action.value.action_id 路由
  - form 内按钮：event.action.name 路由（form_submit，无 action_id）
"""

from app.models.draft import Draft
from app.models.goal import Goal
from app.models.phase import Phase
from app.models.task import Task
from app.models.theme import Theme
from app.services.draft_app_svc import DraftAppSvc
from app.services.schedule_app_svc import ScheduleAppSvc
from tests._factory import make_tree

_WEBHOOK = "/webhook/feishu/card"

_PLAN = {
    "goal": {
        "name": "知识库构建",
        "description": "test",
        "time_range_start": "2026-07-01",
        "time_range_end": "2026-09-30",
        "scheduled_start_date": "2026-07-02",
    },
    "themes": [
        {
            "name": "知识获取",
            "type": "learning",
            "phases": [
                {
                    "name": "阶段1",
                    "sort_order": 1,
                    "tasks": [{"name": "任务1", "sort_order": 1}],
                }
            ],
        }
    ],
}


def _seed_draft(db_session) -> str:
    return DraftAppSvc(db_session).create(user_id="u1", story_type="plan", content=_PLAN).draft_id


# ===== Story1: 确认方案（form 外 action_id 路由）=====


def test_story1_confirm_via_webhook(client, db_session):
    """story1_确认方案 webhook -> PlanAppSvc.confirm 落库建 goal/theme/phase/task + 删 draft。"""
    draft_id = _seed_draft(db_session)
    payload = {
        "event": {
            "context": {"open_message_id": "om_s1"},
            "action": {"value": {"action_id": "story1_确认方案", "draft_id": draft_id}},
        }
    }
    resp = client.post(_WEBHOOK, json=payload)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["draft_deleted"] is True
    assert data["themes_created"] == 1
    assert data["phases_created"] == 1
    assert data["tasks_created"] == 1
    # draft 已删
    assert db_session.query(Draft).filter_by(id=draft_id).count() == 0
    # goal/theme/phase/task 已建
    assert db_session.query(Goal).count() == 1
    assert db_session.query(Theme).count() == 1
    assert db_session.query(Phase).count() == 1
    assert db_session.query(Task).count() == 1


def test_story1_confirm_missing_draft_id(client):
    """story1_确认方案 缺 draft_id -> 1002。"""
    payload = {
        "event": {
            "context": {"open_message_id": "om_s1"},
            "action": {"value": {"action_id": "story1_确认方案"}},
        }
    }
    resp = client.post(_WEBHOOK, json=payload)
    assert resp.status_code == 200
    assert resp.json()["code"] == 1002


# ===== Story2: 下一步（form 内 btn_name 路由）=====


def test_story2_next_btn_via_webhook(client, db_session, monkeypatch):
    """story2 next_btn form_submit -> 从 form_value 取勾选 themes -> patch_to_card_b_async。"""
    goal, themes, phases = make_tree(db_session, n_themes=2, phases_per_theme=1)
    # mock card_registry 反查 goal_id
    monkeypatch.setattr(
        "app.webhook.feishu_card.get_card_context",
        lambda msg_id: {"type": "schedule_a", "goal_id": goal.id},
    )
    # mock patch_to_card_b_async（不真调 feishu）
    patch_calls = []

    def _fake_patch(message_id, theme_ids, goal_id):
        patch_calls.append((message_id, theme_ids, goal_id))

    monkeypatch.setattr(ScheduleAppSvc, "patch_to_card_b_async", _fake_patch)

    payload = {
        "event": {
            "context": {"open_message_id": "om_s2"},
            "action": {
                "name": "next_btn",
                "form_value": {
                    f"theme_{themes[0].id}": True,
                    f"theme_{themes[1].id}": False,
                },
            },
        }
    }
    resp = client.post(_WEBHOOK, json=payload)
    assert resp.status_code == 200, resp.text
    # patch_to_card_b_async 被 BackgroundTasks 调用
    assert len(patch_calls) == 1
    assert patch_calls[0][0] == "om_s2"
    assert patch_calls[0][1] == [themes[0].id]
    assert patch_calls[0][2] == goal.id


def test_story2_next_btn_no_themes_selected(client, db_session, monkeypatch):
    """story2 next_btn 未勾选任何专题 -> 1002。"""
    monkeypatch.setattr(
        "app.webhook.feishu_card.get_card_context",
        lambda msg_id: None,
    )
    payload = {
        "event": {
            "context": {"open_message_id": "om_s2"},
            "action": {"name": "next_btn", "form_value": {}},
        }
    }
    resp = client.post(_WEBHOOK, json=payload)
    assert resp.status_code == 200
    assert resp.json()["code"] == 1002


# ===== 双路由分流 + noop =====


def test_form_submit_unknown_name_noop(client):
    """form_submit 未知 btn_name -> noop（form_value 业务归 PR-D）。"""
    payload = {
        "event": {
            "context": {"open_message_id": "om_x"},
            "action": {"name": "unknown_btn", "form_value": {}},
        }
    }
    resp = client.post(_WEBHOOK, json=payload)
    assert resp.status_code == 200
    assert resp.json()["code"] == 0


def test_no_event_noop(client):
    """非 schema 2.0 回调（无 event 字段）-> noop。"""
    payload = {"type": "some_other_type"}
    resp = client.post(_WEBHOOK, json=payload)
    assert resp.status_code == 200
    assert resp.json()["code"] == 0


def test_url_verification_still_works(client):
    """url_verification 验签仍正常（无 event 字段，优先处理）。"""
    payload = {"type": "url_verification", "challenge": "abc123"}
    resp = client.post(_WEBHOOK, json=payload)
    assert resp.status_code == 200
    assert resp.json() == {"challenge": "abc123"}
