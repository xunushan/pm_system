"""定时巡检（APScheduler）：兜底机制（doc/03 §3.2/3.4）。

巡检项（每天最多 1 次，Redis 去重 ``supervisor:notified:{kind}:{entity_id}:{date}``）：
  1. scheduled_start_date 到了未激活 -> 推提醒"你计划今天开始，要激活吗"-> 跳 Story 2
  2. deadline 临近（前1天/当天）-> 进度提醒 + 跳 H5 页面按钮
  3. 未确认计划（10:00）-> 提醒
  4. 未做日终总结（21:00）-> 提醒
  5. 阶段衔接 24h 未响应 -> 再推一次衔接提醒

已暂停实体不巡检（doc/03 §3.4）。卡顿监测暂不做（D18）。

测试友好：每个 check 函数独立可测（注入 db + fakeredis），不依赖 scheduler 启动。
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

import redis
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clients.feishu import (
    FeishuClient,
    build_deadline_reminder_card,
    build_phase_linking_card,
    build_plan_reminder_card,
    build_start_date_reminder_card,
    build_summary_reminder_card,
)
from app.config import settings
from app.core.card_registry import set_card_context
from app.core.redis_client import get_redis
from app.core.times import now_utc_naive, parse_iso_naive
from app.db.session import SessionLocal
from app.models.daily_record import DailyRecord
from app.models.goal import Goal
from app.models.phase import Phase
from app.supervisor import linking
from app.supervisor.constants import DEFAULT_CHAT_ID
from app.supervisor.event_bus import LINKING_PUSHED_KEY, NOTIFIED_KEY

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None

# 衔接 24h 未响应阈值
_LINKING_TIMEOUT = timedelta(hours=24)


def _is_notified(r: redis.Redis, kind: str, entity_id: str, today: date) -> bool:
    """检查今日是否已推送（Redis 去重，doc/03 §3.4）。"""
    key = NOTIFIED_KEY.format(kind=kind, entity_id=entity_id, date=today.isoformat())
    return r.exists(key) > 0


def _mark_notified(r: redis.Redis, kind: str, entity_id: str, today: date) -> None:
    """标记今日已推送（TTL 2 天，覆盖跨天窗口）。"""
    key = NOTIFIED_KEY.format(kind=kind, entity_id=entity_id, date=today.isoformat())
    r.set(key, "1", ex=86400 * 2)


# ---- 巡检函数（独立可测）----


def check_start_date(
    db: Session,
    redis_client: redis.Redis,
    today: date | None = None,
    feishu: FeishuClient | None = None,
) -> int:
    """scheduled_start_date 到了未激活 -> 推提醒（doc/06 §I Step4）。

    查 goals.scheduled_start_date <= today 且 status='未开始'（已暂停不巡检）。
    每项每天最多 1 次（Redis 去重）。
    """
    today = today or now_utc_naive().date()
    if feishu is None:
        feishu = FeishuClient()
    pushed = 0

    goals = list(
        db.scalars(
            select(Goal).where(
                Goal.scheduled_start_date <= today,
                Goal.status == "未开始",
            )
        )
    )
    for goal in goals:
        if _is_notified(redis_client, "start_date", goal.id, today):
            continue
        card = build_start_date_reminder_card(
            goal_id=goal.id,
            goal_name=goal.name,
            scheduled_start_date=goal.scheduled_start_date.isoformat()
            if goal.scheduled_start_date
            else today.isoformat(),
        )
        try:
            feishu.send_card(DEFAULT_CHAT_ID, card)
            _mark_notified(redis_client, "start_date", goal.id, today)
            pushed += 1
        except Exception:  # noqa: BLE001
            logger.exception("check_start_date: 推送失败 goal=%s", goal.id)
    return pushed


def check_deadline(
    db: Session,
    redis_client: redis.Redis,
    today: date | None = None,
    feishu: FeishuClient | None = None,
) -> int:
    """deadline 临近（前1天/当天）-> 进度提醒（doc/06 §I Step5）。

    查 phases.deadline 在 [today, today+1] 且 status='进行中'（已暂停不巡检）。
    """
    today = today or now_utc_naive().date()
    if feishu is None:
        feishu = FeishuClient()
    pushed = 0

    phases = list(
        db.scalars(
            select(Phase).where(
                Phase.deadline.in_([today, today + timedelta(days=1)]),
                Phase.status == "进行中",
            )
        )
    )
    for phase in phases:
        if _is_notified(redis_client, "deadline", phase.id, today):
            continue
        card = build_deadline_reminder_card(
            phase_id=phase.id,
            phase_name=phase.name,
            deadline=phase.deadline.isoformat() if phase.deadline else "",
            h5_base_url=settings.h5_base_url,
        )
        try:
            feishu.send_card(DEFAULT_CHAT_ID, card)
            _mark_notified(redis_client, "deadline", phase.id, today)
            pushed += 1
        except Exception:  # noqa: BLE001
            logger.exception("check_deadline: 推送失败 phase=%s", phase.id)
    return pushed


def check_unconfirmed_plan(
    db: Session,
    redis_client: redis.Redis,
    today: date | None = None,
    feishu: FeishuClient | None = None,
) -> int:
    """未确认计划 10:00 -> 提醒（doc/06 §I Step6）。

    查今日 daily_records.is_confirmed=0。每项每天最多 1 次。
    """
    today = today or now_utc_naive().date()
    if feishu is None:
        feishu = FeishuClient()
    pushed = 0

    daily = db.scalar(select(DailyRecord).where(DailyRecord.date == today))
    if daily is not None and daily.is_confirmed:
        return 0  # 已确认，无需提醒

    entity_id = daily.id if daily else "none"
    if _is_notified(redis_client, "unconfirmed_plan", entity_id, today):
        return 0

    card = build_plan_reminder_card(today.isoformat())
    try:
        feishu.send_card(DEFAULT_CHAT_ID, card)
        _mark_notified(redis_client, "unconfirmed_plan", entity_id, today)
        pushed += 1
    except Exception:  # noqa: BLE001
        logger.exception("check_unconfirmed_plan: 推送失败 date=%s", today)
    return pushed


def check_missing_summary(
    db: Session,
    redis_client: redis.Redis,
    today: date | None = None,
    feishu: FeishuClient | None = None,
) -> int:
    """未做日终总结 21:00 -> 提醒（doc/06 §I Step7）。

    查今日无 daily_records 或 is_confirmed=0。每项每天最多 1 次。
    """
    today = today or now_utc_naive().date()
    if feishu is None:
        feishu = FeishuClient()
    pushed = 0

    daily = db.scalar(select(DailyRecord).where(DailyRecord.date == today))
    if daily is not None and daily.is_confirmed:
        return 0  # 已确认日终总结，无需提醒

    entity_id = daily.id if daily else "none"
    if _is_notified(redis_client, "missing_summary", entity_id, today):
        return 0

    card = build_summary_reminder_card(today.isoformat())
    try:
        feishu.send_card(DEFAULT_CHAT_ID, card)
        _mark_notified(redis_client, "missing_summary", entity_id, today)
        pushed += 1
    except Exception:  # noqa: BLE001
        logger.exception("check_missing_summary: 推送失败 date=%s", today)
    return pushed


def check_linking_unresponded(
    db: Session,
    redis_client: redis.Redis,
    today: date | None = None,
    feishu: FeishuClient | None = None,
) -> int:
    """阶段衔接 24h 未响应 -> 再推一次（doc/06 §I Step8）。

    逻辑：
      1. 查已完成的 phases（有 activated_at，status='已完成'）
      2. 其下一阶段（sort_order+1）仍 '未开始'（未激活）
      3. Redis LINKING_PUSHED_KEY 有推送记录，且距今 > 24h
      4. 再推一次衔接提醒（Redis 去重 1 次/天）
    """
    today = today or now_utc_naive().date()
    now = now_utc_naive()
    if feishu is None:
        feishu = FeishuClient()
    pushed = 0

    completed_phases = list(
        db.scalars(
            select(Phase).where(
                Phase.activated_at.is_not(None),
                Phase.status == "已完成",
            )
        )
    )
    for phase in completed_phases:
        next_phase = linking.find_next_phase(db, phase.id)
        if next_phase is None or next_phase.status != "未开始":
            continue

        # 检查推送时间是否 > 24h
        key = LINKING_PUSHED_KEY.format(phase_id=phase.id)
        pushed_at_str = redis_client.get(key)
        if pushed_at_str:
            try:
                pushed_at = parse_iso_naive(pushed_at_str)
                if now - pushed_at < _LINKING_TIMEOUT:
                    continue  # 还没到 24h，跳过
            except (ValueError, TypeError):
                logger.warning("check_linking_unresponded: 无法解析推送时间 %s", pushed_at_str)
        # 无推送记录（可能进程重启丢队列）-> 继续推一次

        # 每项每天最多 1 次（去重）
        if _is_notified(redis_client, "linking_unresp", phase.id, today):
            continue

        # 再推一次衔接卡片
        suggested_deadline = linking.compute_suggested_deadline(db, next_phase)
        deadline_str = suggested_deadline.isoformat() if suggested_deadline else ""
        card = build_phase_linking_card(
            completed_phase_name=phase.name,
            next_phase_id=next_phase.id,
            next_phase_name=next_phase.name,
            suggested_deadline=deadline_str,
        )
        try:
            message_id = feishu.send_card(DEFAULT_CHAT_ID, card)
            if message_id:
                set_card_context(message_id, {"type": "phase_linking", "phase_id": next_phase.id})
            _mark_notified(redis_client, "linking_unresp", phase.id, today)
            # 更新推送时间
            redis_client.set(key, now.isoformat(), ex=86400 * 2)
            pushed += 1
        except Exception:  # noqa: BLE001
            logger.exception("check_linking_unresponded: 推送失败 phase=%s", phase.id)
    return pushed


# ---- scheduler 生命周期 ----


def start_scheduler() -> None:
    """启动 APScheduler，注册各巡检 cron job（doc/03 §3.2）。

    幂等：已启动则跳过。在 main.py lifespan startup 调用。
    """
    global _scheduler
    if not settings.supervisor_enabled:
        logger.info("Supervisor scheduler 已禁用（supervisor_enabled=False）")
        return
    if _scheduler is not None:
        return

    sched = BackgroundScheduler(timezone="UTC")

    # 每天巡检函数的包装器：创建独立 session + redis
    def _wrap(check_fn):
        def _run():
            db = SessionLocal()
            r = get_redis()
            try:
                check_fn(db, r)
            except Exception:  # noqa: BLE001
                logger.exception("scheduler job 异常: %s", check_fn.__name__)
            finally:
                db.close()
                r.close()

        return _run

    # cron 时间（UTC）：9:00 start_date/deadline，10:00 plan，21:00 summary，10:00 linking
    sched.add_job(_wrap(check_start_date), "cron", hour=9, id="check_start_date")
    sched.add_job(_wrap(check_deadline), "cron", hour=9, id="check_deadline")
    sched.add_job(_wrap(check_unconfirmed_plan), "cron", hour=10, id="check_unconfirmed_plan")
    sched.add_job(_wrap(check_missing_summary), "cron", hour=21, id="check_missing_summary")
    sched.add_job(_wrap(check_linking_unresponded), "cron", hour=10, id="check_linking_unresponded")

    sched.start()
    _scheduler = sched
    logger.info("Supervisor scheduler started")


def stop_scheduler() -> None:
    """优雅关闭 scheduler。在 main.py lifespan shutdown 调用。"""
    global _scheduler
    if _scheduler is None:
        return
    _scheduler.shutdown(wait=False)
    _scheduler = None
    logger.info("Supervisor scheduler stopped")
