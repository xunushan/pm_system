"""OpenCode 客户端：HTTP POST 下发任务到 opencode serve 端口。

端口动态分配（10000-20000，见《系统架构文档》五）。
启动时机：首次下发智能体任务时（Story3 确认后），非 Story2 激活时。
TODO(Story4A)：实现 dispatch_task / health / shutdown。

S3 桩（接口先行，同 event_bus.emit 桩之理）：
  - dispatch_pre_subtasks：异步执行前置子任务（opencode run）。
  - start_agent_serve：启动 opencode serve 接管智能体任务。
  当前实现为 no-op + 打日志。S4A 换成真 HTTP dispatch + agent_processes 管理。
"""

import logging
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)


class OpenCodeClient:
    """按 workspace 的 opencode serve 端口下发任务。

    S3 桩：dispatch_pre_subtasks / start_agent_serve 为 no-op。
    S4A 替换为真 HTTP dispatch_task / health / shutdown + agent_processes 管理。
    """

    def __init__(self) -> None:
        self.base_url = settings.opencode_base_url

    def dispatch_pre_subtasks(self, subtasks: list[dict[str, Any]]) -> None:
        """异步执行前置子任务（opencode run）。

        S3 桩：no-op + 打日志。S4A 实现真 HTTP POST 到 opencode serve。

        Args:
            subtasks: 前置子任务列表，每项含 id/name/task_id 等。
        """
        logger.info("opencode.dispatch_pre_subtasks (stub): %d subtasks", len(subtasks))

    def start_agent_serve(self, workspace_id: str, task: dict[str, Any] | None = None) -> None:
        """启动 opencode serve 接管智能体任务（动态端口）。

        S3 桩：no-op + 打日志。S4A 实现真启动 + agent_processes 记录 + 心跳。

        Args:
            workspace_id: 工作空间 ID。
            task: 触发启动的智能体任务（含 task_id/name/phase_id）。
        """
        logger.info(
            "opencode.start_agent_serve (stub): workspace=%s task=%s",
            workspace_id,
            task.get("task_id") if task else None,
        )
