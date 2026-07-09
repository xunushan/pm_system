"""事件总线：状态变更事件 -> 进程内异步队列 -> Supervisor handler。

架构决策（已裁决）：进程内异步队列（不依赖 Redis pub/sub）。
  - ``emit(event)`` 在事务内被调用（cascade.py 等），**只做入队**
    （queue.put_nowait，线程安全），立即返回，不阻塞事务（铁律 #3 + 3 秒回调）。
  - dispatcher daemon 线程消费队列，按 ``type`` 路由到 handler。
  - handler 的副作用（推飞书卡片等 IO）在事务外异步执行（此时事务已 commit）。
  - 进程重启丢队列未处理事件：由定时巡检兜底（衔接 24h 未响应会再推；
    事件可从 status_change_log 重建状态）。这是可接受的（单进程单用户）。

接口不变：``emit(event: dict) -> None`` 签名不变，cascade.py / task_app_svc.py
现有 9 处调用零改动，S8 把桩内部换成真分发。

事件类型：
  - phase_completed / theme_completed / goal_completed（完成级联）
  - phase_reverted / theme_reverted / goal_reverted（回退级联）
  - task_completed（任务完成，即时级联由 cascade 处理，事件供扩展）

测试友好：提供 ``dispatch_sync(event)`` 同步分发入口（不经线程，直接调 handler），
以及 ``set_dispatch_func(fn)`` 允许注入自定义分发函数。
"""

from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

# 线程安全队列（emit 入队，dispatcher 出队）
_queue: queue.Queue[dict[str, Any]] = queue.Queue()

# dispatcher 线程
_dispatcher_thread: threading.Thread | None = None
_stop_event = threading.Event()

# 可注入的分发函数（测试用），默认 None -> 用默认路由分发
_dispatch_func: Callable[[dict[str, Any]], None] | None = None

# dispatcher 轮询超时（秒），控制退出响应速度
_POLL_TIMEOUT = 0.5


def emit(event: dict[str, Any]) -> None:
    """发布状态变更事件（入队，不阻塞事务）。

    在事务内被调用（cascade.py:135 等，事务未 commit），只做入队，
    立即返回。dispatcher 线程异步消费并路由到 handler。

    Args:
        event: 事件载荷，需含 ``type``（phase_completed/theme_completed/
            goal_completed/task_completed/phase_reverted/...）与 ``entity_id``。
    """
    _queue.put_nowait(event)
    logger.debug("event_bus.emit queued: %s", event.get("type"))


def dispatch_sync(event: dict[str, Any]) -> None:
    """同步分发单个事件（测试用，不经线程）。

    直接路由到对应 handler，异常被捕获记录（不抛出，与 dispatcher 行为一致）。
    """
    _route(event)


def set_dispatch_func(fn: Callable[[dict[str, Any]], None] | None) -> None:
    """注入自定义分发函数（测试用）。

    设置后 dispatcher 用 fn 代替默认路由；传 None 恢复默认。
    """
    global _dispatch_func
    _dispatch_func = fn


def start_dispatcher() -> None:
    """启动 dispatcher daemon 线程。

    幂等：已启动则跳过。在 main.py lifespan startup 调用。
    """
    global _dispatcher_thread
    if _dispatcher_thread is not None and _dispatcher_thread.is_alive():
        return
    _stop_event.clear()
    _dispatcher_thread = threading.Thread(
        target=_run_dispatcher, daemon=True, name="supervisor-dispatcher"
    )
    _dispatcher_thread.start()
    logger.info("Supervisor event_bus dispatcher started")


def stop_dispatcher() -> None:
    """停止 dispatcher（优雅关闭）。

    设置停止信号，等待线程退出（最多 5 秒）。在 main.py lifespan shutdown 调用。
    """
    global _dispatcher_thread
    if _dispatcher_thread is None:
        return
    _stop_event.set()
    _dispatcher_thread.join(timeout=5)
    _dispatcher_thread = None
    logger.info("Supervisor event_bus dispatcher stopped")


def _run_dispatcher() -> None:
    """dispatcher 线程主循环：消费队列 -> 分发。"""
    while not _stop_event.is_set():
        try:
            event = _queue.get(timeout=_POLL_TIMEOUT)
        except queue.Empty:
            continue
        try:
            _route(event)
        except Exception:  # noqa: BLE001
            logger.exception("event_bus dispatcher error handling: %s", event)


def _route(event: dict[str, Any]) -> None:
    """路由单个事件到对应 handler。

    若注入了自定义分发函数则用它，否则按 type 路由到 handlers 模块。
    回退事件（phase_reverted 等）仅记日志（S8 范围，doc/03 事件即时表只列完成事件）。
    """
    if _dispatch_func is not None:
        _dispatch_func(event)
        return

    event_type = event.get("type")
    entity_id = event.get("entity_id")
    if not event_type or not entity_id:
        logger.warning("event_bus: 事件缺少 type/entity_id: %s", event)
        return

    # 回退事件：仅记日志（S8 范围，重点在完成衔接）
    if event_type.endswith("_reverted"):
        logger.info("event_bus: 回退事件 %s entity=%s（no-op）", event_type, entity_id)
        return

    # 完成事件 -> 路由到 handlers（独立 session，事务已 commit）
    from app.supervisor import handlers

    handler_map = {
        "phase_completed": handlers.on_phase_completed,
        "theme_completed": handlers.on_theme_completed,
        "goal_completed": handlers.on_goal_completed,
    }
    handler = handler_map.get(event_type)
    if handler is None:
        logger.debug("event_bus: 无 handler for %s（task_completed 等即时级联已处理）", event_type)
        return

    handler(entity_id)


# 记录衔接推送时间的 Redis key 前缀（handlers + scheduler 共用）
LINKING_PUSHED_KEY = "supervisor:linking:pushed:{phase_id}"

# 巡检去重 key 前缀
NOTIFIED_KEY = "supervisor:notified:{kind}:{entity_id}:{date}"
