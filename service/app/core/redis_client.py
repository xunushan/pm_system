"""Redis 客户端工厂：创建 Redis 连接的公共函数。

复用件（CLAUDE.md §11）：task_timeout / supervisor handlers / scheduler 统一调用
``get_redis()``，避免 ``_get_redis`` 三处重复定义。

测试用 fakeredis（注入 redis_client 参数，不依赖此工厂）。
"""

import redis

from app.config import settings


def get_redis() -> redis.Redis:
    """创建 Redis 客户端（每次调用新建连接，避免线程安全问题）。

    decode_responses=True：返回 str 而非 bytes，与巡检去重 key 逻辑一致。
    """
    return redis.from_url(settings.redis_url, decode_responses=True)
