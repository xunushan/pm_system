"""Redis 卡片注册表：message_id -> 业务上下文映射（P2 路由缺口落地）。

schema 2.0 的 form_submit 按钮无 value/action_id（doc/09 V1/V8），
webhook 收到 form_submit 回调时只能靠 ``event.context.open_message_id`` 反查
该卡片关联的业务 ID（task_id/daily_id/goal_id 等）。
本模块在 Service 推卡（``send_card`` 返回 message_id）时写入映射，
webhook 回调时读取映射。

Key: ``card:{message_id}``
Value: JSON ``{"type": "...", "goal_id": "...", ...}``
TTL: 7 天（卡片交互窗口内有效，过期清理）

复用件模式参考 ``app/core/task_timeout.py``。测试用 fakeredis（注入 redis_client 参数）。
"""

import json
import logging

import redis

from app.core.redis_client import get_redis

logger = logging.getLogger(__name__)

_KEY_PREFIX = "card"
_DEFAULT_TTL = 604800  # 7 天


def set_card_context(
    message_id: str,
    context: dict,
    ttl: int = _DEFAULT_TTL,
    redis_client: redis.Redis | None = None,
) -> None:
    """SET ``card:{message_id}`` = JSON(context) EX ttl。

    推卡方法 ``send_card`` 返回 message_id 后调用，记录卡片关联的业务上下文
    （type/goal_id/task_id/daily_id 等）。供后续 form_submit 回调反查（P2 路由缺口）。

    Args:
        message_id: 飞书消息 ID（send_card 返回值）。
        context: 业务上下文字典，至少含 ``type``，按卡片类型附带业务 ID。
        ttl: 过期秒数（默认 7 天）。
        redis_client: 可选注入的 Redis 客户端（测试用 fakeredis）。
    """
    r = redis_client or get_redis()
    key = f"{_KEY_PREFIX}:{message_id}"
    r.set(key, json.dumps(context, ensure_ascii=False), ex=ttl)
    logger.info("Redis SET %s (ttl=%ds)", key, ttl)
    if redis_client is None:
        r.close()


def get_card_context(
    message_id: str,
    redis_client: redis.Redis | None = None,
) -> dict | None:
    """GET ``card:{message_id}`` 的上下文（dict），不存在返回 None。

    webhook 收到 form_submit 回调时调用，从 ``event.context.open_message_id``
    反查业务 ID（如 story2 next_btn 反查 goal_id）。
    """
    r = redis_client or get_redis()
    key = f"{_KEY_PREFIX}:{message_id}"
    val = r.get(key)
    if redis_client is None:
        r.close()
    if val is None:
        return None
    return json.loads(val)


def delete_card_context(
    message_id: str,
    redis_client: redis.Redis | None = None,
) -> None:
    """DEL ``card:{message_id}``。"""
    r = redis_client or get_redis()
    key = f"{_KEY_PREFIX}:{message_id}"
    r.delete(key)
    logger.info("Redis DEL %s", key)
    if redis_client is None:
        r.close()
