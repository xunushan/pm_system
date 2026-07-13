"""Story2 集成测试：webhook confirm_btn 确认调度回调（入口 B）。

schema 2.0 下确认调度按钮是 form_submit（name=confirm_btn，卡片 B）。
date_picker form_value name=dl_theme_<theme_id>，值"2026-07-15 +0800"（doc/09 V7）。
goal_id 靠 message_id 反查 card_registry（type=schedule_b）。
"""

from app.models.phase import Phase
from app.models.workspace import Workspace
from tests._factory import make_tree

_WEBHOOK = "/webhook/feishu/card"


def _confirm_btn_payload(message_id, form_value):
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


def test_webhook_schedule_confirm_activates(client, db_session, monkeypatch):
    """webhook confirm_btn (schedule_b) -> 激活 phase + 级联 + 建 workspace。"""
    goal, themes, _ = make_tree(db_session)
    db_session.flush()

    # mock card_registry 反查 goal_id（schedule_b = 卡片 B 确认调度）
    monkeypatch.setattr(
        "app.webhook.feishu_card.get_card_context",
        lambda msg_id: {"type": "schedule_b", "goal_id": goal.id},
    )

    payload = _confirm_btn_payload(
        "om_test",
        {f"dl_theme_{themes[0].id}": "2026-07-15 +0800"},
    )
    resp = client.post(_WEBHOOK, json=payload)
    assert resp.status_code == 200, resp.text
    # 方案 B：同步返回 toast + card
    assert resp.json()["toast"]["content"] == "调度已确认"

    assert db_session.query(Phase).filter_by(status="进行中").count() == 1
    assert themes[0].status == "进行中"
    assert goal.status == "进行中"
    assert db_session.query(Workspace).count() == 1


def test_webhook_schedule_confirm_quota_409(client, db_session, monkeypatch):
    """webhook 走同样名额校验 -> 409(1004 并发超限)。"""
    goal, themes, phases = make_tree(db_session, n_themes=4, phases_per_theme=1)
    for p in phases[:3]:
        p.status = "进行中"
    db_session.flush()

    monkeypatch.setattr(
        "app.webhook.feishu_card.get_card_context",
        lambda msg_id: {"type": "schedule_b", "goal_id": goal.id},
    )

    payload = _confirm_btn_payload(
        "om_test",
        {f"dl_theme_{themes[3].id}": "2026-07-15 +0800"},
    )
    resp = client.post(_WEBHOOK, json=payload)
    assert resp.status_code == 409
    assert resp.json()["code"] == 1004


def test_webhook_schedule_confirm_no_card_context(client, db_session, monkeypatch):
    """card_registry 反查 None -> 1002（容错，不崩）。"""
    monkeypatch.setattr(
        "app.webhook.feishu_card.get_card_context",
        lambda msg_id: None,
    )
    payload = _confirm_btn_payload("om_test", {"dl_theme_x": "2026-07-15 +0800"})
    resp = client.post(_WEBHOOK, json=payload)
    assert resp.status_code == 200
    assert resp.json()["code"] == 1002


def test_webhook_unknown_action_returns_noop(client):
    """未知 action_id -> noop。"""
    payload = {"event": {"context": {}, "action": {"value": {"action_id": "unknown.x"}}}}
    resp = client.post(_WEBHOOK, json=payload)
    assert resp.status_code == 200
    assert resp.json()["code"] == 0


def test_webhook_url_verification_echoes_challenge(client):
    """飞书验签：type=url_verification 时原样回 challenge（无 action 字段）。

    飞书配置回调地址时先发此请求确认地址归属，必须返回 {"challenge": "<原值>"}，
    否则飞书报"Challenge code 没有返回"导致回调地址校验失败。
    """
    challenge = "6005fab3-9bac-47ed-b9c6-95589e38c7ef"
    payload = {
        "challenge": challenge,
        "token": "P52zxkv6uVXTwPz3nUvW6f8FAKGW3SUG",
        "type": "url_verification",
    }
    resp = client.post(_WEBHOOK, json=payload)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {"challenge": challenge}
