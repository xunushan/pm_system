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

from app.clients.feishu import FeishuClient, build_done_card, build_weekly_summary_card
from app.clients.fileio import write_weekly_md
from app.core.card_registry import set_card_context
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

    # ---- 推卡入口（schema 2.0，doc/09 §S6）----

    def push_weekly_summary_card(
        self,
        week: str,
        start_date: str,
        end_date: str,
        completed_tasks: list[dict],
        daily_trends: list[dict],
        phase_health: list[dict],
        agent_output_count: int,
        next_week_advice: str,
        chat_id: str,
    ) -> str | None:
        """推周总结卡片（schema 2.0，doc/09 §S6 状态1）。

        事务后异步 IO（铁律 §3#3）：调 build_weekly_summary_card + FeishuClient.send_card。
        send_card 返回 message_id 后存 Redis 映射 card:<message_id> ->
        {type:"weekly_summary", week}，供 PR-D update_card 补全反查（P2 路由缺口落地）。

        注意：已阅按钮是 form 外（action_id=story6_已阅周总结 + week），
        回调直接从 action_value 取 week；本映射为 update_card 补全预留。

        :return: 飞书 message_id（未配置飞书时返回 None）。
        """
        card = build_weekly_summary_card(
            week,
            start_date,
            end_date,
            completed_tasks,
            daily_trends,
            phase_health,
            agent_output_count,
            next_week_advice,
        )
        message_id = FeishuClient().send_card(chat_id, card)
        if message_id:
            set_card_context(message_id, {"type": "weekly_summary", "week": week})
        return message_id

    # ---- 终态卡片构建（纯函数 + _from_db 供 webhook 同步返回）----

    @staticmethod
    def build_weekly_done_card(
        week: str, daily_summary: str, phase_summary: str, agent_files: int
    ) -> dict:
        """构建周总结已阅终态卡片（纯函数，doc/09 §S6 状态2）。

        绿色标题 + "✅ 周总结已阅，已归档" + 本周回顾摘要 + weekly.md 提示。
        供 webhook 同步返回（方案 B）+ refresh_weekly_done_async 异步刷新共用。
        """
        elements = [
            {
                "tag": "markdown",
                "content": (
                    "✅ **周总结已阅，已归档**\n\n"
                    "**本周回顾：**\n"
                    f"· 每日完成：\n{daily_summary}\n"
                    f"· 阶段：\n{phase_summary}\n"
                    f"· 智能体产出：{agent_files} 文件"
                ),
            },
            {"tag": "hr"},
            {
                "tag": "markdown",
                "content": "weekly.md 快照已写入。如需修正数据，前往 H5 页面。",
            },
        ]
        return build_done_card(f"📊 周总结已阅（{week}）", "green", elements)

    @staticmethod
    def build_weekly_done_card_from_db(db: Session, week: str) -> dict:
        """查询 DB 统计数据 + 构建周总结已阅终态卡片（供 webhook 同步调用）。

        内部调 StatsAppSvc 查询 + build_weekly_done_card 组装。
        """
        stats = StatsAppSvc(db).get_weekly_stats("system", week)

        # 每日完成汇总
        daily_lines = []
        for d in stats.daily_stats:
            total = d.completed_count + d.incomplete_count
            daily_lines.append(f"· {d.date.isoformat()}：{d.completed_count}/{total}")
        daily_summary = "\n".join(daily_lines) or "· （无数据）"

        # 阶段进展
        phase_lines = []
        for p in stats.phase_health:
            phase_lines.append(f"· {p.name}：{p.completed}/{p.total} {p.status}")
        phase_summary = "\n".join(phase_lines) or "· （无数据）"

        agent_files = stats.agent_output_stats.total_files

        return WeeklyAppSvc.build_weekly_done_card(week, daily_summary, phase_summary, agent_files)

    # ---- 事务后异步 update_card 刷新终态（doc/09 §通用规则）----

    @staticmethod
    def refresh_weekly_done_async(message_id: str, week: str) -> None:
        """事务后异步刷新周总结卡到已阅态（独立 session，BackgroundTasks 调用）。

        §S6 状态2 已阅：绿色，"✅ 周总结已阅，已归档" + 本周回顾摘要 + weekly.md 提示。
        铁律 §3#3/#4：HTTP 事务后异步，满足飞书 3 秒回调。
        保留给非回调场景（定时任务、事件触发）；webhook 回调走同步返回（方案 B）。
        """
        db = SessionLocal()
        try:
            card = WeeklyAppSvc.build_weekly_done_card_from_db(db, week)
            FeishuClient().update_card(message_id, card)
        except Exception:
            logger.exception("refresh_weekly_done_async 失败: week=%s", week)
        finally:
            db.close()
