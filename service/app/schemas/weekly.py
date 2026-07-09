"""周总结请求/响应模型。详见《服务API文档 v2.0》3.6。

GET  /weekly/summary/generate   周总结统计预查询（只读，纯 Service 代码）
POST /weekly/summary/confirm     确认周总结（标记 is_confirmed + 异步写 weekly.md）

统计字段复用 app.schemas.stats.PhaseHealthItem。文案/下周建议由 pm-summary LLM 生成，
S6 不碰 LLM（铁律 §3#1）。supervisor_linking_status 由 Story8 填充，S6 占位返回 None。
"""

from datetime import date

from pydantic import BaseModel

from app.schemas.stats import PhaseHealthItem


class DateRange(BaseModel):
    """ISO 周日期范围（周一 ~ 周日）。"""

    start: date
    end: date


class DailyStatsItem(BaseModel):
    """本周单日完成趋势。"""

    date: date
    is_confirmed: bool = False
    completed_count: int = 0
    incomplete_count: int = 0


class AgentOutputStats(BaseModel):
    """本周智能体产出统计（workspace_progress 聚合）。"""

    total_files: int = 0
    by_type: dict[str, int] = {}


class SubtaskStatsItem(BaseModel):
    """前置/后置子任务统计。"""

    total: int = 0
    completed: int = 0
    pending: int = 0


class SubtaskStats(BaseModel):
    pre: SubtaskStatsItem
    post: SubtaskStatsItem


class SupervisorLinkingStatus(BaseModel):
    """Supervisor 衔接状态（doc/04 3.6）。

    下周建议参考此状态（pm-summary LLM）。真逻辑由 Story8 Supervisor 实现，
    S6 占位返回 None（接口先行，S8 替换为真查询）。
    """

    next_phase: str | None = None
    suggested_deadline: date | None = None


class WeeklyStatsData(BaseModel):
    """GET /weekly/summary/generate 响应（纯查询，无 LLM）。

    同 GET /stats/weekly 响应（doc/04 3.11）。
    """

    week: str
    date_range: DateRange
    daily_stats: list[DailyStatsItem] = []
    phase_health: list[PhaseHealthItem] = []
    agent_output_stats: AgentOutputStats
    subtask_stats: SubtaskStats
    # TODO(Story8): Supervisor 衔接状态由 S8 填充，S6 占位 None
    supervisor_linking_status: SupervisorLinkingStatus | None = None


class WeeklyConfirmRequest(BaseModel):
    """POST /weekly/summary/confirm 请求。"""

    week: str


class WeeklyConfirmData(BaseModel):
    """POST /weekly/summary/confirm 响应。"""

    week: str
    confirmed: bool
    weekly_md_path: str | None = None
