"""定时巡检（APScheduler）：兜底机制。

巡检项（每天最多 1 次，Redis 去重 supervisor:notified:{type}:{entity_id}:{date}）：
  - scheduled_start_date 到了未激活 -> 推提醒（1次/天）
  - deadline 临近（前1天/当天）-> 进度提醒（1次/天）
  - 当日未确认计划 10:00 / 当日未做日终总结 21:00
  - 阶段衔接 24h 未响应 -> 再推一次
已暂停实体不巡检。卡顿监测暂不做（D18）。
详见《系统架构文档》3.2/3.4。
"""

from app.config import settings


def start_scheduler() -> None:
    """TODO(Story8)：启动 APScheduler，注册各巡检 job。"""
    if not settings.supervisor_enabled:
        return
    raise NotImplementedError("Story8 实现 - 见 doc/03 3.2")


def stop_scheduler() -> None:
    """TODO(Story8)：关闭 scheduler。"""
    raise NotImplementedError("Story8 实现")
