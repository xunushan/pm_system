"""Story4A 单元测试：Redis 超时监控（fakeredis）。"""

import fakeredis

from app.core.task_timeout import del_task_timeout, get_task_timeout, set_task_timeout


def _make_redis():
    """创建 fakeredis 客户端。"""
    return fakeredis.FakeRedis(decode_responses=True)


def test_set_task_timeout(db_session):
    """SET task_timeout:{task_id} EX 7200。"""
    r = _make_redis()
    set_task_timeout("task_001", "ws_001", ttl=7200, redis_client=r)
    val = get_task_timeout("task_001", redis_client=r)
    assert val == "ws_001"
    # 验证 TTL
    ttl = r.ttl("task_timeout:task_001")
    assert 7190 <= ttl <= 7200


def test_del_task_timeout(db_session):
    """DEL task_timeout:{task_id}。"""
    r = _make_redis()
    set_task_timeout("task_001", "ws_001", redis_client=r)
    assert get_task_timeout("task_001", redis_client=r) == "ws_001"

    del_task_timeout("task_001", redis_client=r)
    assert get_task_timeout("task_001", redis_client=r) is None


def test_get_task_timeout_not_exists(db_session):
    """key 不存在 -> None。"""
    r = _make_redis()
    assert get_task_timeout("nonexistent", redis_client=r) is None


def test_set_task_timeout_overwrite(db_session):
    """重复 SET 覆盖旧值。"""
    r = _make_redis()
    set_task_timeout("task_001", "ws_001", redis_client=r)
    set_task_timeout("task_001", "ws_002", redis_client=r)
    assert get_task_timeout("task_001", redis_client=r) == "ws_002"
