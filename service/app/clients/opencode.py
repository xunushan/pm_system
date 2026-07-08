"""OpenCode 客户端：HTTP POST 下发任务到 opencode serve 端口。

端口动态分配（10000-20000，见《系统架构文档》五）。
启动时机：首次下发智能体任务时（Story3 确认后），非 Story2 激活时。
TODO(Story4A)：实现 dispatch_task / health / shutdown。
"""

from app.config import settings


class OpenCodeClient:
    """TODO：按 workspace 的 opencode serve 端口下发任务。"""

    def __init__(self) -> None:
        self.base_url = settings.opencode_base_url
