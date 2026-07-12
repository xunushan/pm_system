"""card_registry 单元测试：message_id -> 业务上下文映射（P2 路由缺口落地）。

用 fakeredis（注入 redis_client 参数），不依赖真实 Redis。
"""

import json

import fakeredis

from app.core.card_registry import (
    delete_card_context,
    get_card_context,
    set_card_context,
)


def test_set_and_get_card_context():
    r = fakeredis.FakeRedis(decode_responses=True)
    set_card_context("om_123", {"type": "schedule_a", "goal_id": "g1"}, redis_client=r)
    ctx = get_card_context("om_123", redis_client=r)
    assert ctx == {"type": "schedule_a", "goal_id": "g1"}


def test_get_card_context_not_exist():
    r = fakeredis.FakeRedis(decode_responses=True)
    assert get_card_context("om_none", redis_client=r) is None


def test_delete_card_context():
    r = fakeredis.FakeRedis(decode_responses=True)
    set_card_context("om_456", {"type": "daily_plan"}, redis_client=r)
    delete_card_context("om_456", redis_client=r)
    assert get_card_context("om_456", redis_client=r) is None


def test_card_context_stored_as_json():
    """card:<message_id> 存的是 JSON 字符串（decode_responses=True 返回 str）。"""
    r = fakeredis.FakeRedis(decode_responses=True)
    set_card_context("om_789", {"type": "weekly_summary", "week": "2026-W28"}, redis_client=r)
    raw = r.get("card:om_789")
    assert raw is not None
    assert json.loads(raw) == {"type": "weekly_summary", "week": "2026-W28"}
