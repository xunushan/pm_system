"""事件总线：状态变更事件 -> 即时编排 Supervisor。

事件类型（doc/03 3.2）：
  - 阶段 status->已完成  -> 衔接下一阶段
  - 专题完成            -> 推卡片列未完成专题
  - 智能体产出回调       -> 即时级联 + 验收卡片
  - 任务 status->已完成 -> 即时级联

接口先行（CLAUDE.md §11）：S1 起建 emit() 桩，S8 换成真分发。
Story1 的 confirm 只创建初始状态实体（未开始/待执行），**不产生完成事件**，
故 S1 不调 emit()。桩的存在即交付物，接口不变，S8 合并后事件自动接上。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def emit(event: dict[str, Any]) -> None:
    """发布状态变更事件（桩实现：no-op，仅记日志）。

    S8 将替换为进程内 pub/sub 或基于 Redis 的真分发。调用方接口不变。

    Args:
        event: 事件载荷，建议含 `type`（phase_completed/theme_completed/
            task_completed/agent_output）与 `entity_id`。
    """
    logger.info("event_bus.emit (stub): %s", event)
