"""事件处理：阶段/专题/目标完成 -> 衔接编排 + 推卡片（doc/03 §3.3）。

确定性代码（非 LLM，铁律 §3#1）：
  - on_phase_completed: 查下一阶段 + 推算 deadline + 推衔接卡片 + Redis 记推送时间
  - on_theme_completed: 推卡片列出未完成的其他专题（单选，专题无序）
  - on_goal_completed: 推目标完成通知卡片（纯通知）

handler 在 dispatcher 线程中执行（事务外异步），用独立 SessionLocal 读 DB。
副作用（推飞书卡片等 IO）在此执行，满足铁律 #3（事务后异步）。

测试友好：handler 接受可选 db/feishu/redis_client 参数，注入测试实例。
"""

from __future__ import annotations

import logging

import redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clients.feishu import (
    FeishuClient,
    build_goal_completed_card,
    build_phase_linking_card,
    build_theme_completed_card,
)
from app.core.card_registry import set_card_context
from app.core.redis_client import get_redis
from app.core.times import now_utc_naive
from app.db.session import SessionLocal
from app.models.goal import Goal
from app.models.phase import Phase
from app.models.theme import Theme
from app.supervisor import linking
from app.supervisor.constants import DEFAULT_CHAT_ID
from app.supervisor.event_bus import LINKING_PUSHED_KEY

logger = logging.getLogger(__name__)

# 衔接推送记录 TTL（2 天，覆盖 24h 巡检窗口）
_LINKING_TTL = 86400 * 2


def on_phase_completed(
    phase_id: str,
    db: Session | None = None,
    feishu: FeishuClient | None = None,
    redis_client: redis.Redis | None = None,
) -> None:
    """阶段完成事件 -> 推衔接卡片（doc/03 §3.3）。

    Step1: 查同专题 sort_order+1 下一阶段（强约束自动锁定）
    Step2: 推算建议 deadline（剩余时间/剩余阶段数）
    Step3: 推衔接卡片（飞书，带 deadline + 确认激活/暂不激活）
    Step4: Redis 记衔接推送时间（24h 未响应巡检用）

    无下一阶段 -> 走专题完成检查（该事件由 cascade 单独 emit，此处 no-op）。
    """
    own_session = db is None
    if own_session:
        db = SessionLocal()
    own_redis = redis_client is None
    if own_redis:
        redis_client = get_redis()
    if feishu is None:
        feishu = FeishuClient()

    try:
        phase = db.get(Phase, phase_id)
        if phase is None:
            logger.warning("on_phase_completed: phase 不存在 %s", phase_id)
            return

        # Step1: 查下一阶段
        next_phase = linking.find_next_phase(db, phase_id)
        if next_phase is None:
            # 无下一阶段 -> 专题完成事件会单独处理（cascade emit theme_completed）
            logger.info("on_phase_completed: phase %s 无下一阶段（专题将完成）", phase_id)
            return

        # Step2: 推算建议 deadline
        suggested_deadline = linking.compute_suggested_deadline(db, next_phase)
        deadline_str = suggested_deadline.isoformat() if suggested_deadline else ""

        # Step3: 推衔接卡片
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
        except Exception:  # noqa: BLE001
            logger.exception("on_phase_completed: 推衔接卡片失败 phase=%s", phase_id)

        # Step4: Redis 记衔接推送时间（24h 巡检用）
        key = LINKING_PUSHED_KEY.format(phase_id=phase_id)
        redis_client.set(key, now_utc_naive().isoformat(), ex=_LINKING_TTL)
        logger.info("on_phase_completed: 衔接卡片已推送 phase=%s next=%s", phase_id, next_phase.id)
    finally:
        if own_session:
            db.close()
        if own_redis:
            redis_client.close()


def on_theme_completed(
    theme_id: str,
    db: Session | None = None,
    feishu: FeishuClient | None = None,
) -> None:
    """专题完成事件 -> 推卡片列出同 goal 下未完成的其他专题（doc/03 §3.2）。

    专题无序，单选。用户选后跳 Story2 激活（patch 填 deadline）。
    无其他未完成专题 -> 不推卡片（goal 完成事件单独处理）。
    """
    own_session = db is None
    if own_session:
        db = SessionLocal()
    if feishu is None:
        feishu = FeishuClient()

    try:
        theme = db.get(Theme, theme_id)
        if theme is None:
            logger.warning("on_theme_completed: theme 不存在 %s", theme_id)
            return

        # 查同 goal 下未完成的其他专题（专题无序）
        other_themes = list(
            db.scalars(
                select(Theme).where(
                    Theme.goal_id == theme.goal_id,
                    Theme.id != theme_id,
                    Theme.status != "已完成",
                    Theme.status != "已暂停",
                )
            )
        )
        if not other_themes:
            logger.info("on_theme_completed: theme %s 无其他未完成专题（goal 将完成）", theme_id)
            return

        # 推卡片（列出未完成专题，单选）
        card = build_theme_completed_card(
            completed_theme_name=theme.name,
            other_themes=[{"theme_id": t.id, "name": t.name, "type": t.type} for t in other_themes],
        )
        try:
            feishu.send_card(DEFAULT_CHAT_ID, card)
        except Exception:  # noqa: BLE001
            logger.exception("on_theme_completed: 推卡片失败 theme=%s", theme_id)
        logger.info("on_theme_completed: 专题完成卡片已推送 theme=%s", theme_id)
    finally:
        if own_session:
            db.close()


def on_goal_completed(
    goal_id: str,
    db: Session | None = None,
    feishu: FeishuClient | None = None,
) -> None:
    """目标完成事件 -> 推目标完成通知卡片（纯通知，无按钮）。"""
    own_session = db is None
    if own_session:
        db = SessionLocal()
    if feishu is None:
        feishu = FeishuClient()

    try:
        goal = db.get(Goal, goal_id)
        if goal is None:
            logger.warning("on_goal_completed: goal 不存在 %s", goal_id)
            return

        card = build_goal_completed_card(goal.name)
        try:
            feishu.send_card(DEFAULT_CHAT_ID, card)
        except Exception:  # noqa: BLE001
            logger.exception("on_goal_completed: 推通知卡片失败 goal=%s", goal_id)
        logger.info("on_goal_completed: 目标完成通知已推送 goal=%s", goal_id)
    finally:
        if own_session:
            db.close()
