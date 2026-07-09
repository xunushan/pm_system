"""Story8 单元测试：定时巡检（scheduler.py）。

测试每个巡检函数（独立可测，注入 db + fakeredis）：
  - check_start_date: scheduled_start_date 到了未激活 -> 推提醒
  - check_deadline: deadline 临近 -> 推进度提醒
  - check_unconfirmed_plan: 未确认计划 -> 提醒
  - check_missing_summary: 未做日终总结 -> 提醒
  - check_linking_unresponded: 24h 未响应 -> 再推
  - Redis 去重：重复调不重复推
  - 已暂停实体不巡检
"""

from datetime import date, timedelta
from uuid import uuid4

from app.core.times import now_utc_naive
from app.models.daily_record import DailyRecord
from app.supervisor import scheduler
from app.supervisor.event_bus import LINKING_PUSHED_KEY, NOTIFIED_KEY
from tests._factory import make_tree

_TODAY = date(2026, 7, 10)


class FakeFeishu:
    def __init__(self):
        self.cards = []

    def send_card(self, chat_id, card):
        self.cards.append(card)


def test_check_start_date_pushes_reminder(db_session, fake_redis):
    """scheduled_start_date 到了未激活 -> 推提醒。"""
    goal, themes, phases = make_tree(db_session, n_themes=1, phases_per_theme=1)
    goal.scheduled_start_date = _TODAY
    goal.status = "未开始"
    db_session.flush()
    feishu = FakeFeishu()

    pushed = scheduler.check_start_date(db_session, fake_redis, today=_TODAY, feishu=feishu)

    assert pushed == 1
    assert len(feishu.cards) == 1
    # 去重 key 已设
    key = NOTIFIED_KEY.format(kind="start_date", entity_id=goal.id, date=_TODAY.isoformat())
    assert fake_redis.exists(key)


def test_check_start_date_dedup(db_session, fake_redis):
    """Redis 去重：重复调不重复推。"""
    goal, themes, phases = make_tree(db_session)
    goal.scheduled_start_date = _TODAY
    goal.status = "未开始"
    db_session.flush()
    feishu = FakeFeishu()

    scheduler.check_start_date(db_session, fake_redis, today=_TODAY, feishu=feishu)
    pushed2 = scheduler.check_start_date(db_session, fake_redis, today=_TODAY, feishu=feishu)

    assert pushed2 == 0
    assert len(feishu.cards) == 1  # 只推了第一次


def test_check_start_date_skips_active_goal(db_session, fake_redis):
    """已激活（进行中）的 goal 不推。"""
    goal, themes, phases = make_tree(db_session, goal_status="进行中")
    goal.scheduled_start_date = _TODAY
    db_session.flush()

    pushed = scheduler.check_start_date(db_session, fake_redis, today=_TODAY, feishu=FakeFeishu())
    assert pushed == 0


def test_check_start_date_skips_paused_goal(db_session, fake_redis):
    """已暂停的 goal 不巡检。"""
    goal, themes, phases = make_tree(db_session)
    goal.scheduled_start_date = _TODAY
    goal.status = "已暂停"
    db_session.flush()

    pushed = scheduler.check_start_date(db_session, fake_redis, today=_TODAY, feishu=FakeFeishu())
    assert pushed == 0


def test_check_deadline_pushes_reminder(db_session, fake_redis):
    """deadline 临近（今天/明天）-> 推进度提醒。"""
    goal, themes, phases = make_tree(db_session, n_themes=1, phases_per_theme=1)
    phases[0].status = "进行中"
    phases[0].deadline = _TODAY
    phases[0].activated_at = _TODAY
    db_session.flush()
    feishu = FakeFeishu()

    pushed = scheduler.check_deadline(db_session, fake_redis, today=_TODAY, feishu=feishu)

    assert pushed == 1
    assert len(feishu.cards) == 1


def test_check_deadline_tomorrow(db_session, fake_redis):
    """deadline 明天到 -> 也推（前1天提醒）。"""
    goal, themes, phases = make_tree(db_session, n_themes=1, phases_per_theme=1)
    phases[0].status = "进行中"
    phases[0].deadline = _TODAY + timedelta(days=1)
    db_session.flush()

    pushed = scheduler.check_deadline(db_session, fake_redis, today=_TODAY, feishu=FakeFeishu())
    assert pushed == 1


def test_check_deadline_skips_not_due(db_session, fake_redis):
    """deadline 还远 -> 不推。"""
    goal, themes, phases = make_tree(db_session, n_themes=1, phases_per_theme=1)
    phases[0].status = "进行中"
    phases[0].deadline = _TODAY + timedelta(days=7)
    db_session.flush()

    pushed = scheduler.check_deadline(db_session, fake_redis, today=_TODAY, feishu=FakeFeishu())
    assert pushed == 0


def test_check_deadline_skips_paused(db_session, fake_redis):
    """已暂停阶段不巡检。"""
    goal, themes, phases = make_tree(db_session, n_themes=1, phases_per_theme=1)
    phases[0].status = "已暂停"
    phases[0].deadline = _TODAY
    db_session.flush()

    pushed = scheduler.check_deadline(db_session, fake_redis, today=_TODAY, feishu=FakeFeishu())
    assert pushed == 0


def test_check_unconfirmed_plan_pushes(db_session, fake_redis):
    """今日计划未确认 -> 推提醒。"""
    daily = DailyRecord(
        id=str(uuid4()), date=_TODAY, week="2026-W28", push_source="manual", is_confirmed=False
    )
    db_session.add(daily)
    db_session.flush()

    pushed = scheduler.check_unconfirmed_plan(
        db_session, fake_redis, today=_TODAY, feishu=FakeFeishu()
    )
    assert pushed == 1


def test_check_unconfirmed_plan_skips_confirmed(db_session, fake_redis):
    """今日计划已确认 -> 不推。"""
    daily = DailyRecord(
        id=str(uuid4()), date=_TODAY, week="2026-W28", push_source="manual", is_confirmed=True
    )
    db_session.add(daily)
    db_session.flush()

    pushed = scheduler.check_unconfirmed_plan(
        db_session, fake_redis, today=_TODAY, feishu=FakeFeishu()
    )
    assert pushed == 0


def test_check_unconfirmed_plan_no_record_pushes(db_session, fake_redis):
    """今日无 daily_record -> 推提醒。"""
    pushed = scheduler.check_unconfirmed_plan(
        db_session, fake_redis, today=_TODAY, feishu=FakeFeishu()
    )
    assert pushed == 1


def test_check_missing_summary_pushes(db_session, fake_redis):
    """未做日终总结 -> 推提醒。"""
    pushed = scheduler.check_missing_summary(
        db_session, fake_redis, today=_TODAY, feishu=FakeFeishu()
    )
    assert pushed == 1


def test_check_missing_summary_skips_confirmed(db_session, fake_redis):
    """日终总结已确认 -> 不推。"""
    daily = DailyRecord(
        id=str(uuid4()), date=_TODAY, week="2026-W28", push_source="manual", is_confirmed=True
    )
    db_session.add(daily)
    db_session.flush()

    pushed = scheduler.check_missing_summary(
        db_session, fake_redis, today=_TODAY, feishu=FakeFeishu()
    )
    assert pushed == 0


def test_check_linking_unresponded_pushes(db_session, fake_redis):
    """阶段衔接 24h 未响应 -> 再推。"""
    goal, themes, phases = make_tree(db_session, n_themes=1, phases_per_theme=2)
    phases[0].status = "已完成"
    phases[0].activated_at = _TODAY - timedelta(days=2)
    phases[0].completed_at = now_utc_naive() - timedelta(hours=25)
    db_session.flush()
    feishu = FakeFeishu()

    # Redis 记衔接推送时间（25h 前）
    key = LINKING_PUSHED_KEY.format(phase_id=phases[0].id)
    fake_redis.set(key, (now_utc_naive() - timedelta(hours=25)).isoformat(), ex=86400 * 2)

    pushed = scheduler.check_linking_unresponded(db_session, fake_redis, feishu=feishu)

    assert pushed == 1
    assert len(feishu.cards) == 1


def test_check_linking_unresponded_skips_recent(db_session, fake_redis):
    """衔接推送 < 24h -> 不再推。"""
    goal, themes, phases = make_tree(db_session, n_themes=1, phases_per_theme=2)
    phases[0].status = "已完成"
    phases[0].activated_at = _TODAY - timedelta(days=1)
    phases[0].completed_at = now_utc_naive() - timedelta(hours=2)
    db_session.flush()

    # Redis 记衔接推送时间（2h 前）
    key = LINKING_PUSHED_KEY.format(phase_id=phases[0].id)
    fake_redis.set(key, (now_utc_naive() - timedelta(hours=2)).isoformat(), ex=86400 * 2)

    pushed = scheduler.check_linking_unresponded(db_session, fake_redis, feishu=FakeFeishu())
    assert pushed == 0


def test_check_linking_unresponded_skips_activated_next(db_session, fake_redis):
    """下一阶段已激活 -> 不推。"""
    goal, themes, phases = make_tree(db_session, n_themes=1, phases_per_theme=2)
    phases[0].status = "已完成"
    phases[0].activated_at = _TODAY - timedelta(days=2)
    phases[1].status = "进行中"  # 已激活
    db_session.flush()

    key = LINKING_PUSHED_KEY.format(phase_id=phases[0].id)
    fake_redis.set(key, (now_utc_naive() - timedelta(hours=25)).isoformat(), ex=86400 * 2)

    pushed = scheduler.check_linking_unresponded(db_session, fake_redis, feishu=FakeFeishu())
    assert pushed == 0


def test_check_linking_unresponded_dedup(db_session, fake_redis):
    """衔接未响应巡检每天最多 1 次。"""
    goal, themes, phases = make_tree(db_session, n_themes=1, phases_per_theme=2)
    phases[0].status = "已完成"
    phases[0].activated_at = _TODAY - timedelta(days=2)
    phases[0].completed_at = now_utc_naive() - timedelta(hours=25)
    db_session.flush()

    key = LINKING_PUSHED_KEY.format(phase_id=phases[0].id)
    fake_redis.set(key, (now_utc_naive() - timedelta(hours=25)).isoformat(), ex=86400 * 2)

    feishu = FakeFeishu()
    pushed1 = scheduler.check_linking_unresponded(
        db_session, fake_redis, today=_TODAY, feishu=feishu
    )
    pushed2 = scheduler.check_linking_unresponded(
        db_session, fake_redis, today=_TODAY, feishu=feishu
    )

    assert pushed1 == 1
    assert pushed2 == 0
    assert len(feishu.cards) == 1
