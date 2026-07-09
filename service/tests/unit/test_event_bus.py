"""Story8 单元测试：事件总线（event_bus.py）。

测试：
  - emit 入队不阻塞（队列有事件）
  - dispatch_sync 路由到正确 handler（phase_completed -> on_phase_completed）
  - dispatch_sync 回退事件 no-op（仅日志）
  - dispatch_sync 无 handler 的事件不崩溃
  - dispatch_sync 缺少 type/entity_id 不崩溃
  - set_dispatch_func 注入自定义分发
  - start/stop_dispatcher 生命周期
"""

from app.supervisor import event_bus
from app.supervisor.event_bus import (
    dispatch_sync,
    emit,
    set_dispatch_func,
    start_dispatcher,
    stop_dispatcher,
)


def _drain_queue():
    """清空事件队列（Queue 无 clear 方法，逐个 get）。"""
    while not event_bus._queue.empty():
        try:
            event_bus._queue.get_nowait()
        except Exception:  # noqa: BLE001
            break


def test_emit_enqueues_event():
    """emit 把事件放入队列，不阻塞。"""
    _drain_queue()
    emit({"type": "phase_completed", "entity_id": "p1"})
    assert event_bus._queue.qsize() == 1
    event = event_bus._queue.get_nowait()
    assert event["type"] == "phase_completed"
    assert event["entity_id"] == "p1"


def test_emit_multiple_events():
    """多次 emit 多次入队。"""
    _drain_queue()
    emit({"type": "phase_completed", "entity_id": "p1"})
    emit({"type": "theme_completed", "entity_id": "t1"})
    emit({"type": "goal_completed", "entity_id": "g1"})
    assert event_bus._queue.qsize() == 3


def test_dispatch_sync_routes_phase_completed(monkeypatch):
    """dispatch_sync 把 phase_completed 路由到 on_phase_completed。"""
    called = []

    def fake_handler(entity_id):
        called.append(entity_id)

    monkeypatch.setattr("app.supervisor.handlers.on_phase_completed", fake_handler)
    set_dispatch_func(None)  # 恢复默认路由（conftest 设了 no-op）
    try:
        dispatch_sync({"type": "phase_completed", "entity_id": "p1"})
    finally:
        set_dispatch_func(lambda _e: None)
    assert called == ["p1"]


def test_dispatch_sync_routes_theme_completed(monkeypatch):
    """dispatch_sync 把 theme_completed 路由到 on_theme_completed。"""
    called = []

    def fake_handler(entity_id):
        called.append(entity_id)

    monkeypatch.setattr("app.supervisor.handlers.on_theme_completed", fake_handler)
    set_dispatch_func(None)
    try:
        dispatch_sync({"type": "theme_completed", "entity_id": "t1"})
    finally:
        set_dispatch_func(lambda _e: None)
    assert called == ["t1"]


def test_dispatch_sync_routes_goal_completed(monkeypatch):
    """dispatch_sync 把 goal_completed 路由到 on_goal_completed。"""
    called = []

    def fake_handler(entity_id):
        called.append(entity_id)

    monkeypatch.setattr("app.supervisor.handlers.on_goal_completed", fake_handler)
    set_dispatch_func(None)
    try:
        dispatch_sync({"type": "goal_completed", "entity_id": "g1"})
    finally:
        set_dispatch_func(lambda _e: None)
    assert called == ["g1"]


def test_dispatch_sync_reverted_noop(monkeypatch):
    """回退事件（phase_reverted 等）no-op，不调 handler。"""
    called = []

    def fake_handler(entity_id):
        called.append(entity_id)

    monkeypatch.setattr("app.supervisor.handlers.on_phase_completed", fake_handler)
    set_dispatch_func(None)
    try:
        dispatch_sync({"type": "phase_reverted", "entity_id": "p1"})
    finally:
        set_dispatch_func(lambda _e: None)
    assert called == []


def test_dispatch_sync_no_handler_event(monkeypatch):
    """task_completed 等无 handler 的事件 -> 不崩溃（即时级联已处理）。"""
    set_dispatch_func(None)
    try:
        dispatch_sync({"type": "task_completed", "entity_id": "t1"})
    finally:
        set_dispatch_func(lambda _e: None)


def test_dispatch_sync_missing_fields_no_crash():
    """事件缺少 type/entity_id -> 不崩溃（仅警告日志）。"""
    set_dispatch_func(None)
    try:
        dispatch_sync({"type": "phase_completed"})
        dispatch_sync({"entity_id": "p1"})
        dispatch_sync({})
    finally:
        set_dispatch_func(lambda _e: None)


def test_set_dispatch_func_injection():
    """set_dispatch_func 注入自定义分发函数。"""
    called = []
    set_dispatch_func(lambda e: called.append(e))
    dispatch_sync({"type": "phase_completed", "entity_id": "p1"})
    assert called == [{"type": "phase_completed", "entity_id": "p1"}]
    # 恢复默认
    set_dispatch_func(None)


def test_start_stop_dispatcher_lifecycle():
    """start_dispatcher / stop_dispatcher 生命周期（线程启动/停止）。"""
    start_dispatcher()
    assert event_bus._dispatcher_thread is not None
    assert event_bus._dispatcher_thread.is_alive()

    # 幂等：重复 start 跳过
    start_dispatcher()

    stop_dispatcher()
    assert event_bus._dispatcher_thread is None


def test_dispatcher_consumes_events(monkeypatch):
    """dispatcher 线程消费队列事件 -> 调 handler。"""
    _drain_queue()
    called = []

    def fake_handler(entity_id):
        called.append(entity_id)

    monkeypatch.setattr("app.supervisor.handlers.on_phase_completed", fake_handler)

    # 恢复默认分发（conftest 设了 no-op）
    set_dispatch_func(None)
    try:
        start_dispatcher()
        emit({"type": "phase_completed", "entity_id": "p1"})

        # 等待 dispatcher 消费（轮询）
        import time

        for _ in range(20):
            if called:
                break
            time.sleep(0.1)

        assert called == ["p1"]
    finally:
        stop_dispatcher()
        set_dispatch_func(lambda _e: None)


def test_dispatcher_exception_does_not_crash(monkeypatch):
    """handler 抛异常 -> dispatcher 不崩溃，继续处理后续事件。"""
    _drain_queue()
    called = []

    def bad_handler(entity_id):
        if entity_id == "bad":
            raise RuntimeError("boom")
        called.append(entity_id)

    monkeypatch.setattr("app.supervisor.handlers.on_phase_completed", bad_handler)
    set_dispatch_func(None)
    try:
        start_dispatcher()
        emit({"type": "phase_completed", "entity_id": "bad"})
        emit({"type": "phase_completed", "entity_id": "good"})

        import time

        for _ in range(20):
            if "good" in called:
                break
            time.sleep(0.1)

        # 第二个事件仍被处理（异常不崩溃）
        assert "good" in called
    finally:
        stop_dispatcher()
        set_dispatch_func(lambda _e: None)
