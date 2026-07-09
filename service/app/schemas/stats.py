"""统计请求/响应模型。详见《服务API文档 v2.0》统计节。

GET /api/v1/stats/daily   获取日统计（日终/周总结共用统计查询核心）
"""

from datetime import date

from pydantic import BaseModel


class TaskStatItem(BaseModel):
    """任务统计项。"""

    task_id: str
    name: str
    theme_name: str


class PhaseHealthItem(BaseModel):
    """阶段健康度。"""

    phase_id: str
    name: str
    completed: int
    total: int
    rate: float
    status: str


class DailyStatsData(BaseModel):
    """GET /stats/daily 响应。"""

    date: date
    daily_id: str | None = None
    is_confirmed: bool = False
    completed_tasks: list[TaskStatItem] = []
    incomplete_tasks: list[TaskStatItem] = []
    phase_health: list[PhaseHealthItem] = []
    active_phase_count: int = 0
    global_active_limit: int = 3
