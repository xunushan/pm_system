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
    """story1_确认方案 webhook -> PlanAppSvc.confirm 落库建 goal/theme/phase/task + 删 draft。

    方案 B：同步返回 toast + card（绿色已确认态），不再异步 update_card。
    """
    draft_id = _seed_draft(db_session)
    payload = {
        "event": {
            "context": {"open_message_id": "om_s1"},
            "action": {"value": {"action_id": "story1_确认方案", "draft_id": draft_id}},
        }
    }
    resp = client.post(_WEBHOOK, json=payload)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # 同步返回 toast + card（方案 B）
    assert body["toast"]["type"] == "success"
    assert body["toast"]["content"] == "方案已确认"
    card = body["card"]["data"]
    assert card["header"]["template"] == "green"
    assert "方案已确认" in card["body"]["elements"][0]["content"]
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
    """story2 next_btn form_submit -> 同步返回卡片 B（方案 B）。

    从 form_value 取勾选 themes -> 查 DB -> build_schedule_card_b -> card.data 返回。
    """
    goal, themes, phases = make_tree(db_session, n_themes=2, phases_per_theme=1)
    # mock card_registry 反查 goal_id
    monkeypatch.setattr(
        "app.webhook.feishu_card.get_card_context",
        lambda msg_id: {"type": "schedule_a", "goal_id": goal.id},
    )
    # mock set_card_context（不写真实 Redis）
    monkeypatch.setattr("app.webhook.feishu_card.set_card_context", lambda *a, **kw: None)

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
    body = resp.json()
    # 同步返回 toast + card（方案 B）
    assert body["toast"]["content"] == "请填 deadline"
    card = body["card"]["data"]
    # 卡片 B 是蓝色（保留按钮）
    assert card["header"]["template"] == "blue"
    # 含 date_picker（dl_theme_<theme_id>）
    form = card["body"]["elements"][1]
    date_pickers = [e for e in form["elements"] if e.get("tag") == "date_picker"]
    assert len(date_pickers) == 1
    assert date_pickers[0]["name"] == f"dl_theme_{themes[0].id}"


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
