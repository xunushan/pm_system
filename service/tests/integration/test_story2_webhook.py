"""Story2 集成测试：webhook schedule.confirm 回调（入口 B）。

飞书 3 秒超时：回调仅 DB 写+级联后立即返回，工作空间初始化异步。
"""

from app.models.phase import Phase
from app.models.workspace import Workspace
from tests._factory import make_tree

_WEBHOOK = "/webhook/feishu/card"


def _card_value(goal_id, items):
    """构造 schema 2.0 卡片回调 payload（doc/09 V2：event.action.value）。"""
    return {
        "event": {
            "context": {"open_message_id": "om_test"},
            "action": {
                "value": {
                    "action_id": "schedule.confirm",
                    "user_id": "u1",
                    "goal_id": goal_id,
                    "items": items,
                }
            },
        }
    }


def test_webhook_schedule_confirm_activates(client, db_session):
    """webhook schedule.confirm -> 激活 phase + 级联 + 建 workspace。"""
    goal, themes, _ = make_tree(db_session)
    db_session.flush()

    payload = _card_value(
        goal.id,
        [{"theme_id": themes[0].id, "managed": True, "deadline": "2026-07-15"}],
    )
    resp = client.post(_WEBHOOK, json=payload)
    assert resp.status_code == 200, resp.text
    assert resp.json()["code"] == 0

    assert db_session.query(Phase).filter_by(status="进行中").count() == 1
    assert themes[0].status == "进行中"
    assert goal.status == "进行中"
    assert db_session.query(Workspace).count() == 1


def test_webhook_schedule_confirm_quota_409(client, db_session):
    """webhook 走同样名额校验 -> 409(1004 并发超限)。"""
    goal, themes, phases = make_tree(db_session, n_themes=4, phases_per_theme=1)
    for p in phases[:3]:
        p.status = "进行中"
    db_session.flush()

    payload = _card_value(
        goal.id,
        [{"theme_id": themes[3].id, "managed": True, "deadline": "2026-07-15"}],
    )
    resp = client.post(_WEBHOOK, json=payload)
    assert resp.status_code == 409
    assert resp.json()["code"] == 1004


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
