"""Redis 超时监控：下发智能体任务时 SET 超时 key，验收通过/重试时 DEL。

doc/02 §2.17：
  下发智能体任务时：SET task_timeout:{task_id} EX 7200（2小时）
  验收通过/重试时：DEL task_timeout:{task_id}
  Redis KeyExpirationEvent 触发：飞书通知"智能体执行超时"

测试用 fakeredis（注入 redis_client 或 patch _get_redis）。
"""

import logging

import redis

from app.config import settings

logger = logging.getLogger(__name__)

_KEY_PREFIX = "task_timeout"
_DEFAULT_TTL = 7200  # 2 小时


def _get_redis() -> redis.Redis:
    """创建 Redis 客户端（每次调用新建连接，避免线程安全问题）。"""
    return redis.from_url(settings.redis_url, decode_responses=True)


def set_task_timeout(
    task_id: str,
    workspace_id: str,
    ttl: int = _DEFAULT_TTL,
    redis_client: redis.Redis | None = None,
) -> None:
    """SET task_timeout:{task_id} = workspace_id EX ttl。

    Args:
        task_id: 智能体任务 ID。
        workspace_id: 工作空间 ID（超时回调时定位工作空间）。
        ttl: 超时秒数（默认 7200 = 2 小时）。
        redis_client: 可选注入的 Redis 客户端（测试用 fakeredis）。
    """
    r = redis_client or _get_redis()
    key = f"{_KEY_PREFIX}:{task_id}"
    r.set(key, workspace_id, ex=ttl)
    logger.info("Redis SET %s (ttl=%ds)", key, ttl)
    if redis_client is None:
        r.close()


def del_task_timeout(task_id: str, redis_client: redis.Redis | None = None) -> None:
    """DEL task_timeout:{task_id}。

    验收通过或重试时调用，清除超时 key。
    """
    r = redis_client or _get_redis()
    key = f"{_KEY_PREFIX}:{task_id}"
    r.delete(key)
    logger.info("Redis DEL %s", key)
    if redis_client is None:
        r.close()


def get_task_timeout(task_id: str, redis_client: redis.Redis | None = None) -> str | None:
    """GET task_timeout:{task_id} 的值（workspace_id），不存在返回 None。"""
    r = redis_client or _get_redis()
    key = f"{_KEY_PREFIX}:{task_id}"
    val = r.get(key)
    if redis_client is None:
        r.close()
    return val
