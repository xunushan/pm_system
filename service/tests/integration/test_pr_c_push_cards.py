"""PR-C 推卡入口 + 映射存储集成测试。

4 个推卡方法：PlanAppSvc.push_overview_card / ScheduleAppSvc.push_schedule_card /
DailyAppSvc.push_daily_plan_card / WeeklyAppSvc.push_weekly_summary_card。
ScheduleAppSvc.patch_to_card_b_async（story2 next_btn 的 update_card）。

验证：调对 builder + send_card 返回 message_id + Redis 映射存储（P2 路由缺口落地）。
"""

from unittest.mock import patch

import fakeredis
import pytest
from sqlalchemy.orm import sessionmaker

from app.clients.feishu import FeishuClient
from app.core.card_registry import get_card_context
from app.services import schedule_app_svc
from app.services.daily_app_svc import DailyAppSvc
from app.services.plan_app_svc import PlanAppSvc
from app.services.schedule_app_svc import ScheduleAppSvc
from app.services.weekly_app_svc import WeeklyAppSvc
from tests._factory import make_tree


@pytest.fixture()
def fake_redis_card(monkeypatch):
    """注入 fakeredis 到 card_registry（推卡存映射 + 反查共用）。"""
    r = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr("app.core.card_registry.get_redis", lambda: r)
    return r


# ===== PlanAppSvc.push_overview_card =====


def test_push_overview_card(db_session, fake_redis_card):
    """push_overview_card -> build_plan_overview_card + send_card + 映射。"""
    with patch("app.services.plan_app_svc.FeishuClient") as MockFeishu:
        instance = MockFeishu.return_value
        instance.send_card.return_value = "om_plan"
        msg_id = PlanAppSvc(db_session).push_overview_card(
            goal_name="知识库构建",
            theme_count=4,
            phase_count=12,
            task_count=36,
            draft_id="d1",
            chat_id="oc_test",
        )
    assert msg_id == "om_plan"
    instance.send_card.assert_called_once()
    chat_id, card = instance.send_card.call_args[0]
    assert chat_id == "oc_test"
    assert card["schema"] == "2.0"
    assert card["header"]["template"] == "blue"
    # 映射存储（P2 路由缺口落地）
    ctx = get_card_context("om_plan", redis_client=fake_redis_card)
    assert ctx == {"type": "plan_overview", "draft_id": "d1"}


def test_push_overview_card_not_configured(db_session, fake_redis_card):
    """飞书未配置 -> send_card 返回 None，不存映射。"""
    with patch("app.services.plan_app_svc.FeishuClient") as MockFeishu:
        instance = MockFeishu.return_value
        instance.send_card.return_value = None
        msg_id = PlanAppSvc(db_session).push_overview_card(
            goal_name="x",
            theme_count=1,
            phase_count=1,
            task_count=1,
            draft_id="d2",
            chat_id="oc_test",
        )
    assert msg_id is None


# ===== ScheduleAppSvc.push_schedule_card =====


def test_push_schedule_card(db_session, fake_redis_card):
    """push_schedule_card -> build_schedule_card_a + send_card + 映射（goal_id）。"""
    goal, themes, phases = make_tree(db_session, n_themes=2, phases_per_theme=1)
    themes_data = [
        {"theme_id": t.id, "name": t.name, "type": t.type, "goal_id": goal.id} for t in themes
    ]
    with patch("app.services.schedule_app_svc.FeishuClient") as MockFeishu:
        instance = MockFeishu.return_value
        instance.send_card.return_value = "om_sched"
        msg_id = ScheduleAppSvc(db_session).push_schedule_card(
            goal_name=goal.name, themes=themes_data, chat_id="oc_test", h5_url="http://h5"
        )
    assert msg_id == "om_sched"
    instance.send_card.assert_called_once()
    card = instance.send_card.call_args[0][1]
    assert card["schema"] == "2.0"
    # 卡片 A 含 checker + next_btn form_submit
    form = card["body"]["elements"][1]
    assert form["tag"] == "form"
    assert form["name"] == "schedule_form_a"
    # 映射存储（next_btn 回调反查 goal_id）
    ctx = get_card_context("om_sched", redis_client=fake_redis_card)
    assert ctx == {"type": "schedule_a", "goal_id": goal.id}


# ===== DailyAppSvc.push_daily_plan_card =====


def test_push_daily_plan_card(db_session, fake_redis_card):
    """push_daily_plan_card -> build_daily_plan_card + send_card + 映射。"""
    with patch("app.services.daily_app_svc.FeishuClient") as MockFeishu:
        instance = MockFeishu.return_value
        instance.send_card.return_value = "om_daily"
        msg_id = DailyAppSvc(db_session).push_daily_plan_card(
            date_str="2026-07-10",
            candidate_tasks=[{"task_id": "t1", "name": "任务1", "executor": "human"}],
            prerequisites=[{"subtask_id": "s1", "name": "前置1"}],
            chat_id="oc_test",
        )
    assert msg_id == "om_daily"
    instance.send_card.assert_called_once()
    card = instance.send_card.call_args[0][1]
    assert card["schema"] == "2.0"
    form = card["body"]["elements"][1]
    assert form["tag"] == "form"
    assert form["name"] == "daily_plan_form"
    ctx = get_card_context("om_daily", redis_client=fake_redis_card)
    assert ctx == {"type": "daily_plan"}


# ===== WeeklyAppSvc.push_weekly_summary_card =====


def test_push_weekly_summary_card(db_session, fake_redis_card):
    """push_weekly_summary_card -> build_weekly_summary_card + send_card + 映射。"""
    with patch("app.services.weekly_app_svc.FeishuClient") as MockFeishu:
        instance = MockFeishu.return_value
        instance.send_card.return_value = "om_weekly"
        msg_id = WeeklyAppSvc(db_session).push_weekly_summary_card(
            week="2026-W28",
            start_date="2026-07-06",
            end_date="2026-07-12",
            completed_tasks=[{"date": "2026-07-06", "task_name": "任务1", "executor": "human"}],
            daily_trends=[{"date": "2026-07-06", "weekday": "周一", "completed": 1, "total": 2}],
            phase_health=[{"name": "阶段1", "completed": 1, "total": 2, "status": "进行中"}],
            agent_output_count=3,
            next_week_advice="继续推进",
            chat_id="oc_test",
        )
    assert msg_id == "om_weekly"
    instance.send_card.assert_called_once()
    card = instance.send_card.call_args[0][1]
    assert card["schema"] == "2.0"
    # 已阅按钮是 form 外（behaviors callback）
    btn = card["body"]["elements"][-1]
    assert btn["tag"] == "button"
    assert btn["behaviors"][0]["value"]["action_id"] == "story6_已阅周总结"
    ctx = get_card_context("om_weekly", redis_client=fake_redis_card)
    assert ctx == {"type": "weekly_summary", "week": "2026-W28"}


# ===== ScheduleAppSvc.patch_to_card_b_async（story2 next_btn 的 update_card）=====


def test_patch_to_card_b_async(client, db_session, monkeypatch):
    """patch_to_card_b_async -> 查 phases + build_schedule_card_b + update_card。"""
    goal, themes, phases = make_tree(db_session, n_themes=2, phases_per_theme=1)
    monkeypatch.setattr(
        schedule_app_svc,
        "SessionLocal",
        sessionmaker(bind=db_session.bind, expire_on_commit=False),
    )
    with patch.object(FeishuClient, "update_card") as mock_update:
        ScheduleAppSvc.patch_to_card_b_async("om_patch", [themes[0].id], goal.id)
    mock_update.assert_called_once()
    message_id, card = mock_update.call_args[0]
    assert message_id == "om_patch"
    assert card["schema"] == "2.0"
    # 卡片 B 有 date_picker + confirm_btn form_submit
    form = card["body"]["elements"][1]
    assert form["tag"] == "form"
    assert form["name"] == "schedule_form_b"


def test_patch_to_card_b_async_no_pending_phases(client, db_session, monkeypatch):
    """patch_to_card_b_async 无未开始阶段 -> 不调 update_card。"""
    goal, themes, phases = make_tree(db_session, n_themes=1, phases_per_theme=1)
    phases[0].status = "进行中"  # 无未开始
    db_session.flush()
    monkeypatch.setattr(
        schedule_app_svc,
        "SessionLocal",
        sessionmaker(bind=db_session.bind, expire_on_commit=False),
    )
    with patch.object(FeishuClient, "update_card") as mock_update:
        ScheduleAppSvc.patch_to_card_b_async("om_patch", [themes[0].id], goal.id)
    mock_update.assert_not_called()
