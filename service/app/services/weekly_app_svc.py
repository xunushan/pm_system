"""WeeklyAppSvc：周总结（Story6，doc/01 §Story6 / doc/04 §3.6）。

两个方法：
  - generate_summary：只读统计预查询（复用 StatsAppSvc.get_weekly_stats），供 pm-summary LLM。
  - confirm_summary：事务 INSERT/UPDATE weekly_records SET is_confirmed=1 -> COMMIT；
    事务后异步写 weekly.md 快照。

铁律（CLAUDE.md §3）：
  - Service 不调 LLM（§3#1）：统计纯查询；文案/下周建议是 pm-summary Skill（S6 不碰 LLM）。
  - 纯回顾不改状态（§3#2/#7）：周总结不修改任何 task/phase 状态，无级联。
  - 事务内禁 IO/HTTP（§3#3）：write_weekly_md 事务后异步。
  - 飞书 3 秒超时（§3#4）：confirm 仅 DB 写后立即返回，write_weekly_md 走 BackgroundTasks。
  - DB 唯一真相源（§3#5）：weekly.md 是快照，不反向同步。
"""

import logging
from uuid import uuid4

from sqlalchemy.orm import Session

from app.clients.fileio import write_weekly_md
from app.core.exceptions import ConflictError
from app.core.times import now_utc_naive
from app.db.session import SessionLocal
from app.models.weekly_record import WeeklyRecord
from app.repositories.weekly_record import WeeklyRecordRepository
from app.schemas.weekly import WeeklyConfirmData, WeeklyStatsData
from app.services.stats_app_svc import StatsAppSvc

logger = logging.getLogger(__name__)


class WeeklyAppSvc:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.weekly_repo = WeeklyRecordRepository(db)

    # ---- GET /weekly/summary/generate (Story6) ----

    def generate_summary(self, user_id: str, week: str) -> WeeklyStatsData:
        """周总结统计预查询（只读，纯 Service 代码）。

        统计查询复用 StatsAppSvc.get_weekly_stats。文案/下周建议由 pm-summary LLM 生成，
        S6 不碰 LLM（铁律 §3#1）。不级联（纯回顾，不改任何状态）。
        """
        return StatsAppSvc(self.db).get_weekly_stats(user_id, week)

    # ---- POST /weekly/summary/confirm (Story6) ----

    def confirm_summary(self, week: str) -> WeeklyConfirmData:
        """确认周总结（"已阅"归档）。不级联（纯回顾），仅写快照 + 标记 is_confirmed。

        事务（doc/04 §3.6）：
          1. INSERT/UPDATE weekly_records SET is_confirmed=1, confirmed_at=now
          2. COMMIT（<200ms）

        事务后异步（路由层 BackgroundTasks 调 write_weekly_md_async）：
          3. 写 weekly.md 快照（纯文件 IO）
        """
        # 解析 week -> date_range（校验格式 + 取日期范围）
        start, end = StatsAppSvc._parse_week(week)

        existing = self.weekly_repo.get_by_week(week)
        if existing is not None:
            if existing.is_confirmed:
                raise ConflictError(f"周总结已确认: {week}")
            existing.is_confirmed = True
            existing.confirmed_at = now_utc_naive()
        else:
            rec = WeeklyRecord(
                id=str(uuid4()),
                week=week,
                date_range_start=start,
                date_range_end=end,
                is_confirmed=True,
                confirmed_at=now_utc_naive(),
            )
            self.weekly_repo.create(rec)

        # COMMIT（<200ms，事务内无 IO/HTTP）
        self.db.commit()

        # 事务后异步写 weekly.md（路由层调 write_weekly_md_async）
        return WeeklyConfirmData(week=week, confirmed=True, weekly_md_path=None)

    @staticmethod
    def write_weekly_md_async(week: str) -> str | None:
        """事务后异步写 weekly.md 快照（独立 session，BackgroundTasks 调用）。

        从 week 反查统计数据 -> 写入 vault/weekly/{week}.md。

        user_id 硬编码为 "system"：当前系统单用户，weekly_records 无 user_id 列
        （与 daily_records 一致），多用户场景需扩展表结构后从此传入。
        """
        db = SessionLocal()
        try:
            stats = StatsAppSvc(db).get_weekly_stats("system", week)
            summary_data = {
                "week": stats.week,
                "date_range": {
                    "start": stats.date_range.start.isoformat(),
                    "end": stats.date_range.end.isoformat(),
                },
                "daily_stats": [
                    {
                        "date": d.date.isoformat(),
                        "is_confirmed": d.is_confirmed,
                        "completed_count": d.completed_count,
                        "incomplete_count": d.incomplete_count,
                    }
                    for d in stats.daily_stats
                ],
                "phase_health": [
                    {
                        "name": p.name,
                        "completed": p.completed,
                        "total": p.total,
                        "rate": p.rate,
                        "status": p.status,
                    }
                    for p in stats.phase_health
                ],
                "agent_output_stats": {
                    "total_files": stats.agent_output_stats.total_files,
                    "by_type": stats.agent_output_stats.by_type,
                },
                "subtask_stats": {
                    "pre": {
                        "total": stats.subtask_stats.pre.total,
                        "completed": stats.subtask_stats.pre.completed,
                        "pending": stats.subtask_stats.pre.pending,
                    },
                    "post": {
                        "total": stats.subtask_stats.post.total,
                        "completed": stats.subtask_stats.post.completed,
                        "pending": stats.subtask_stats.post.pending,
                    },
                },
                "summary": None,
            }
            # 若 weekly_record 存在且有 summary 文本，附上
            rec = WeeklyRecordRepository(db).get_by_week(week)
            if rec is not None and rec.summary:
                summary_data["summary"] = rec.summary
            return write_weekly_md("system", week, summary_data)
        except Exception:
            logger.exception("write_weekly_md_async 失败: %s", week)
            return None
        finally:
            db.close()
