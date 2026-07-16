"""PR-D2 集成测试：全回调 update_card + delete_session + 4 推卡映射补全。

覆盖：
  - 4 推卡入口 card_registry 映射（PR-D1 P1 回归）：phase_linking/handlers+scheduler、
    daily_summary、task_complete、post_confirm
  - 12 回调 update_card 补全（doc/09 §通用规则）：每个回调点击后异步刷终态卡
  - delete_session 接入（D26）：trigger_reject_async 3 次不通过退 session
"""

from datetime import date
from unittest.mock import patch
from uuid import uuid4

import fakeredis
import pytest
from sqlalchemy.orm import sessionmaker

from app.clients.feishu import FeishuClient
from app.core.card_registry import get_card_context
from app.models.daily_record import DailyRecord
from app.models.daily_task import DailyTask
from app.models.task import Task
from app.services import daily_app_svc, plan_app_svc, schedule_app_svc, task_app_svc, weekly_app_svc
from app.services.daily_app_svc import DailyAppSvc
from app.services.plan_app_svc import PlanAppSvc
from app.services.task_app_svc import TaskAppSvc
from tests._factory import make_tree

_WEBHOOK = "/webhook/feishu/card"
_TODAY = date(2026, 7, 6)


# ---- helpers ----


def _form_submit_payload(message_id, btn_name, form_value):
    """构造 schema 2.0 form_submit 回调 payload。"""
    return {
        "event": {
            "context": {"open_message_id": message_id},
            "action": {"name": btn_name, "form_value": form_value},
        }
    }


def _form_outside_payload(message_id, action_id, **extra):
    """构造 form 外按钮回调 payload。"""
    value = {"action_id": action_id, **extra}
    return {
        "event": {
            "context": {"open_message_id": message_id},
            "action": {"value": value},
        }
    }


@pytest.fixture()
def fake_redis_card(monkeypatch):
    """注入 fakeredis 到 card_registry（推卡存映射 + 反查共用）。"""
    r = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr("app.core.card_registry.get_redis", lambda: r)
    return r


def _patch_session_locals(monkeypatch, db_session):
    """统一 monkeypatch 各 service 的 SessionLocal（async 方法用独立 session）。"""
    maker = sessionmaker(bind=db_session.bind, expire_on_commit=False)
    for mod in (plan_app_svc, schedule_app_svc, daily_app_svc, task_app_svc, weekly_app_svc):
        monkeypatch.setattr(mod, "SessionLocal", maker, raising=False)


# ===== Block 1: 4 推卡入口 card_registry 映射（PR-D1 P1 回归）=====


def test_phase_linking_mapping_handlers(db_session, fake_redis_card):
    """on_phase_completed 推衔接卡后存映射 {type:phase_linking, phase_id}。"""
    from app.supervisor.handlers import on_phase_completed

    goal, themes, phases = make_tree(db_session, n_themes=1, phases_per_theme=2)
    phases[0].status = "已完成"
    goal.status = "进行中"
    themes[0].status = "进行中"
    db_session.flush()

    with patch.object(FeishuClient, "send_card", return_value="om_pl") as mock_send:
        on_phase_completed(
            phases[0].id,
            db=db_session,
            feishu=FeishuClient(),
            redis_client=fake_redis_card,
        )
    mock_send.assert_called_once()
    ctx = get_card_context("om_pl", redis_client=fake_redis_card)
    assert ctx is not None
    assert ctx["type"] == "phase_linking"
    assert ctx["phase_id"] == phases[1].id


def test_phase_linking_mapping_scheduler(db_session, fake_redis_card):
    """check_linking_unresponded 推衔接卡后存映射 {type:phase_linking, phase_id}。"""
    from app.supervisor.event_bus import LINKING_PUSHED_KEY
    from app.supervisor.scheduler import check_linking_unresponded

    goal, themes, phases = make_tree(db_session, n_themes=1, phases_per_theme=2)
    phases[0].status = "已完成"
    phases[0].activated_at = _TODAY
    goal.status = "进行中"
    themes[0].status = "进行中"
    db_session.flush()

    # 模拟 24h 前推送过
    key = LINKING_PUSHED_KEY.format(phase_id=phases[0].id)
    fake_redis_card.set(key, "2026-07-05T00:00:00", ex=86400 * 2)

    with patch.object(FeishuClient, "send_card", return_value="om_pl2"):
        check_linking_unresponded(db_session, fake_redis_card, today=_TODAY, feishu=FeishuClient())

    ctx = get_card_context("om_pl2", redis_client=fake_redis_card)
    assert ctx is not None
    assert ctx["type"] == "phase_linking"
    assert ctx["phase_id"] == phases[1].id


def test_push_daily_summary_card_mapping(db_session, fake_redis_card):
    """DailyAppSvc.push_daily_summary_card -> send_card + 存映射 {type:daily_summary, daily_id}。"""
    with patch.object(FeishuClient, "send_card", return_value="om_ds") as mock_send:
        msg_id = DailyAppSvc(db_session).push_daily_summary_card(
            daily_id="d1",
            date_str="2026-07-06",
            completed_tasks=[{"task_id": "t1", "name": "任务1"}],
            incomplete_tasks=[{"task_id": "t2", "name": "任务2"}],
            phase_health=[
                {"name": "阶段1", "completed": 1, "total": 2, "status": "进行中", "rate": 0.5}
            ],
            chat_id="oc_test",
        )
    assert msg_id == "om_ds"
    mock_send.assert_called_once()
    ctx = get_card_context("om_ds", redis_client=fake_redis_card)
    assert ctx == {"type": "daily_summary", "daily_id": "d1"}


def test_push_task_complete_card_mapping(db_session, fake_redis_card):
    """push_task_complete_card -> send_card + 存映射 {type:task_complete, workspace_id}。"""
    with patch.object(FeishuClient, "send_card", return_value="om_tc") as mock_send:
        msg_id = TaskAppSvc(db_session).push_task_complete_card(
            workspace_id="ws1",
            workspace_name="测试空间",
            completed_tasks=[{"name": "任务1", "executor": "human"}],
            pending_tasks=[{"id": "t2", "name": "任务2", "executor": "agent", "is_agent": True}],
            chat_id="oc_test",
        )
    assert msg_id == "om_tc"
    mock_send.assert_called_once()
    ctx = get_card_context("om_tc", redis_client=fake_redis_card)
    assert ctx == {"type": "task_complete", "workspace_id": "ws1"}


def test_push_post_confirm_card_mapping(db_session, fake_redis_card):
    """push_post_confirm_card -> send_card + 存映射 {type:post_confirm, task_id}。"""
    with patch.object(FeishuClient, "send_card", return_value="om_pc") as mock_send:
        msg_id = TaskAppSvc(db_session).push_post_confirm_card(
            task_id="t1",
            task_name="测试任务",
            post_subtasks=[{"id": "p1", "name": "归档"}, {"id": "p2", "name": "更新题库"}],
            chat_id="oc_test",
        )
    assert msg_id == "om_pc"
    mock_send.assert_called_once()
    ctx = get_card_context("om_pc", redis_client=fake_redis_card)
    assert ctx["type"] == "post_confirm"
    assert ctx["task_id"] == "t1"
    assert len(ctx["post_subtasks"]) == 2


def test_push_card_not_configured_no_mapping(db_session, fake_redis_card):
    """send_card 返回 None（飞书未配置）-> 不存映射。"""
    with patch.object(FeishuClient, "send_card", return_value=None):
        msg_id = DailyAppSvc(db_session).push_daily_summary_card(
            daily_id="d1",
            date_str="2026-07-06",
            completed_tasks=[],
            incomplete_tasks=[],
            phase_health=[],
            chat_id="oc_test",
        )
    assert msg_id is None
    assert get_card_context("om_ds", redis_client=fake_redis_card) is None


# ===== Block 2: 全回调 update_card 补全（doc/09 §通用规则）=====


def test_update_card_story1_confirm(client, db_session, monkeypatch):
    """story1_确认方案 -> 同步返回终态卡（§S1 确认后，绿色）。"""
    _patch_session_locals(monkeypatch, db_session)
    mock_confirm = patch.object(PlanAppSvc, "confirm")
    with mock_confirm as mc:
        from app.schemas.plan import PlanConfirmData

        mc.return_value = PlanConfirmData(
            goal_id="g1",
            goal_name="测试目标",
            themes_created=2,
            phases_created=3,
            tasks_created=5,
            draft_deleted=True,
            h5_url="http://h5/plan/g1",
        )
        payload = _form_outside_payload("om_s1", "story1_确认方案", draft_id="d1")
        resp = client.post(_WEBHOOK, json=payload)
    assert resp.status_code == 200
    card = resp.json()["card"]["data"]
    assert card["header"]["template"] == "green"
    assert "测试目标" in card["body"]["elements"][0]["content"]


def test_update_card_schedule_b_confirm(client, db_session, monkeypatch):
    """confirm_btn schedule_b -> 同步返回终态卡（§S2 状态3，绿色）。"""
    goal, themes, _ = make_tree(db_session)
    db_session.flush()
    _patch_session_locals(monkeypatch, db_session)
    monkeypatch.setattr(
        "app.webhook.feishu_card.get_card_context",
        lambda msg_id: {"type": "schedule_b", "goal_id": goal.id},
    )
    payload = _form_submit_payload(
        "om_s2b", "confirm_btn", {f"dl_theme_{themes[0].id}": "2026-07-15 +0800"}
    )
    resp = client.post(_WEBHOOK, json=payload)
    assert resp.status_code == 200
    card = resp.json()["card"]["data"]
    assert card["header"]["template"] == "green"


def test_update_card_daily_plan_confirm(client, db_session, monkeypatch):
    """confirm_btn daily_plan -> 同步返回终态卡（§S3 状态2，绿色）。"""
    goal, themes, phases = make_tree(db_session, n_themes=1, phases_per_theme=1, tasks_per_phase=2)
    phases[0].status = "进行中"
    phases[0].activated_at = _TODAY
    db_session.flush()
    tasks = list(db_session.query(Task).filter_by(phase_id=phases[0].id))
    _patch_session_locals(monkeypatch, db_session)
    monkeypatch.setattr(
        "app.webhook.feishu_card.get_card_context",
        lambda msg_id: {"type": "daily_plan", "date": "2026-07-06", "prerequisites": []},
    )
    payload = _form_submit_payload(
        "om_s3", "confirm_btn", {f"task_{tasks[0].id}": True, f"task_{tasks[1].id}": False}
    )
    resp = client.post(_WEBHOOK, json=payload)
    assert resp.status_code == 200
    card = resp.json()["card"]["data"]
    assert card["header"]["template"] == "green"


def test_update_card_btn_pass(client, db_session, monkeypatch):
    """btn_pass -> 同步返回终态卡（§S4A 场景1，绿色）。"""
    from tests.integration.test_story4a_agent import _make_full_tree

    goal, themes, phases, ws, tasks = _make_full_tree(db_session)
    _patch_session_locals(monkeypatch, db_session)
    monkeypatch.setattr(
        "app.webhook.feishu_card.get_card_context",
        lambda msg_id: {"type": "verification", "task_id": tasks[0].id},
    )
    payload = _form_submit_payload("om_4a", "btn_pass", {})
    resp = client.post(_WEBHOOK, json=payload)
    assert resp.status_code == 200
    card = resp.json()["card"]["data"]
    assert card["header"]["template"] == "green"


def test_update_card_btn_reject_retry(client, db_session, monkeypatch):
    """btn_reject retry -> 同步返回终态卡（§S4A 场景2，橙色）。"""
    from app.models.agent_process import AgentProcess
    from tests.integration.test_story4a_agent import _make_full_tree

    goal, themes, phases, ws, tasks = _make_full_tree(db_session)
    tasks[0].retry_count = 0
    ap = AgentProcess(id=str(uuid4()), workspace_id=ws.id, port=10001, status="running")
    db_session.add(ap)
    db_session.flush()
    _patch_session_locals(monkeypatch, db_session)
    monkeypatch.setattr(
        "app.webhook.feishu_card.get_card_context",
        lambda msg_id: {"type": "verification", "task_id": tasks[0].id},
    )
    with (
        patch.object(task_app_svc.OpenCodeClient, "dispatch_task"),
        patch.object(task_app_svc, "set_task_timeout"),
    ):
        payload = _form_submit_payload("om_4a", "btn_reject", {"feedback": "加注释"})
        resp = client.post(_WEBHOOK, json=payload)
    assert resp.status_code == 200
    card = resp.json()["card"]["data"]
    assert card["header"]["template"] == "orange"


def test_update_card_post_confirm(client, db_session, monkeypatch):
    """confirm_btn post_confirm -> 同步返回终态卡（§S4B 状态2，绿色）。"""
    from tests.integration.test_story4b_tasks import _activate_and_get_task

    goal, themes, phases, task = _activate_and_get_task(db_session)
    task.status = "已完成"
    db_session.flush()
    _patch_session_locals(monkeypatch, db_session)
    monkeypatch.setattr(
        "app.webhook.feishu_card.get_card_context",
        lambda msg_id: {
            "type": "post_confirm",
            "task_id": task.id,
            "post_subtasks": [{"id": "p1", "name": "归档"}],
        },
    )
    with patch.object(task_app_svc.OpenCodeClient, "dispatch_post_subtasks"):
        payload = _form_submit_payload("om_4b", "confirm_btn", {"post_p1": True})
        resp = client.post(_WEBHOOK, json=payload)
    assert resp.status_code == 200
    card = resp.json()["card"]["data"]
    assert card["header"]["template"] == "green"


def test_update_card_daily_summary(client, db_session, monkeypatch):
    """confirm_btn daily_summary -> update_card 刷已确认态（§S5 状态2，绿色）。"""
    from app.core import cascade

    goal, themes, phases = make_tree(db_session, n_themes=1, phases_per_theme=1, tasks_per_phase=1)
    goal.status = "进行中"
    themes[0].status = "进行中"
    phases[0].status = "进行中"
    phases[0].activated_at = _TODAY
    db_session.flush()
    task = db_session.query(Task).filter_by(phase_id=phases[0].id).one()
    task.status = "已完成"
    cascade.cascade_status(db_session, "task", task.id)
    db_session.flush()

    daily = DailyRecord(id=str(uuid4()), date=_TODAY, week="2026-W27", push_source="manual")
    db_session.add(daily)
    db_session.add(DailyTask(id=str(uuid4()), daily_id=daily.id, task_id=task.id))
    db_session.flush()
    _patch_session_locals(monkeypatch, db_session)
    monkeypatch.setattr(
        "app.webhook.feishu_card.get_card_context",
        lambda msg_id: {"type": "daily_summary", "daily_id": daily.id},
    )
    with patch.object(daily_app_svc, "write_daily_md"):
        payload = _form_submit_payload("om_s5", "confirm_btn", {f"task_{task.id}": True})
        resp = client.post(_WEBHOOK, json=payload)
    assert resp.status_code == 200, resp.text
    card = resp.json()["card"]["data"]
    assert card["header"]["template"] == "green"


def test_update_card_task_complete(client, db_session, monkeypatch):
    """confirm_btn task_complete -> 同步返回终态卡（§S4A 场景4，绿色）。"""
    from tests.integration.test_story4a_agent import _make_full_tree

    goal, themes, phases, ws, tasks = _make_full_tree(db_session)
    _patch_session_locals(monkeypatch, db_session)
    monkeypatch.setattr(
        "app.webhook.feishu_card.get_card_context",
        lambda msg_id: {"type": "task_complete", "workspace_id": ws.id},
    )
    with patch.object(TaskAppSvc, "confirm_complete") as mc:
        mc.return_value = {"task_id": tasks[1].id, "status": "已完成"}
        payload = _form_submit_payload("om_tc", "confirm_btn", {f"task_{tasks[1].id}": True})
        resp = client.post(_WEBHOOK, json=payload)
    assert resp.status_code == 200
    mc.assert_called_once()
    card = resp.json()["card"]["data"]
    assert card["header"]["template"] == "green"


def test_update_card_btn_activate(client, db_session, monkeypatch):
    """btn_activate -> 同步返回终态卡（§S8 状态2，绿色）。"""
    goal, themes, phases = make_tree(db_session, n_themes=1, phases_per_theme=2)
    phases[0].status = "已完成"
    goal.status = "进行中"
    themes[0].status = "进行中"
    db_session.flush()
    _patch_session_locals(monkeypatch, db_session)
    monkeypatch.setattr(
        "app.webhook.feishu_card.get_card_context",
        lambda msg_id: {"type": "phase_linking", "phase_id": phases[1].id},
    )
    payload = _form_submit_payload("om_s8", "btn_activate", {"deadline": "2026-07-25 +0800"})
    resp = client.post(_WEBHOOK, json=payload)
    assert resp.status_code == 200
    card = resp.json()["card"]["data"]
    assert card["header"]["template"] == "green"


def test_update_card_btn_defer(client, db_session, monkeypatch):
    """btn_defer -> 同步返回终态卡（§S8 状态3，橙色）。"""
    goal, themes, phases = make_tree(db_session, n_themes=1, phases_per_theme=2)
    phases[0].status = "已完成"
    goal.status = "进行中"
    themes[0].status = "进行中"
    db_session.flush()
    _patch_session_locals(monkeypatch, db_session)
    monkeypatch.setattr(
        "app.webhook.feishu_card.get_card_context",
        lambda msg_id: {"type": "phase_linking", "phase_id": phases[1].id},
    )
    payload = _form_submit_payload("om_s8d", "btn_defer", {})
    resp = client.post(_WEBHOOK, json=payload)
    assert resp.status_code == 200
    card = resp.json()["card"]["data"]
    assert card["header"]["template"] == "orange"


def test_update_card_story6_read(client, db_session, monkeypatch):
    """story6_已阅周总结 -> 同步返回终态卡（§S6 状态2，绿色）。"""
    _patch_session_locals(monkeypatch, db_session)
    with patch.object(weekly_app_svc, "write_weekly_md"):
        payload = _form_outside_payload("om_s6", "story6_已阅周总结", week="2026-W28")
        resp = client.post(_WEBHOOK, json=payload)
    assert resp.status_code == 200
    card = resp.json()["card"]["data"]
    assert card["header"]["template"] == "green"


# ===== Block 4: delete_session 已在 test_task_app_svc.py 覆盖 =====
# test_trigger_reject_async_manual_intervention_path 断言 delete_session 被调


# ===== P2-1: refresh_schedule_done_async h5_url 替换 =====


def test_update_card_schedule_b_h5_url(client, db_session, monkeypatch):
    """confirm_btn schedule_b -> 终态卡含真实 h5_url（非 <h5_url> 占位符）。"""
    goal, themes, _ = make_tree(db_session)
    db_session.flush()
    _patch_session_locals(monkeypatch, db_session)
    monkeypatch.setattr(
        "app.webhook.feishu_card.get_card_context",
        lambda msg_id: {"type": "schedule_b", "goal_id": goal.id},
    )
    monkeypatch.setattr("app.config.settings.h5_base_url", "http://h5test")
    payload = _form_submit_payload(
        "om_s2b", "confirm_btn", {f"dl_theme_{themes[0].id}": "2026-07-15 +0800"}
    )
    resp = client.post(_WEBHOOK, json=payload)
    assert resp.status_code == 200
    card = resp.json()["card"]["data"]
    # 找含"前往配置页"的 markdown element
    md_elements = [
        e
        for e in card["body"]["elements"]
        if e.get("tag") == "markdown" and "前往配置页" in e.get("content", "")
    ]
    assert len(md_elements) == 1
    content = md_elements[0]["content"]
    # 不含字面量 <h5_url> 占位符
    assert "<h5_url>" not in content
    # 含真实 URL
    assert "http://h5test" in content


# ===== P2-2: S4B 全选/全不选 webhook 路由 =====


def test_s4b_select_all(client, db_session, monkeypatch):
    """story4B_全选 -> 同步返回刷新所有 checker checked=true（保留按钮）。"""
    _patch_session_locals(monkeypatch, db_session)
    post_subs = [{"id": "p1", "name": "归档"}, {"id": "p2", "name": "更新题库"}]
    monkeypatch.setattr(
        "app.webhook.feishu_card.get_card_context",
        lambda msg_id: {"type": "post_confirm", "task_id": "t1", "post_subtasks": post_subs},
    )
    payload = _form_outside_payload("om_4b", "story4B_全选", task_id="t1")
    resp = client.post(_WEBHOOK, json=payload)
    assert resp.status_code == 200
    assert resp.json()["toast"]["content"] == "已全选"
    card = resp.json()["card"]["data"]
    # 卡片仍是 blue（非终态，保留按钮）
    assert card["header"]["template"] == "blue"
    # 所有 checker checked=true
    form = card["body"]["elements"][1]
    checkers = [e for e in form["elements"] if e.get("tag") == "checker"]
    assert len(checkers) == 2
    assert all(c["checked"] is True for c in checkers)


def test_s4b_unselect_all(client, db_session, monkeypatch):
    """story4B_全不选 -> 同步返回刷新所有 checker checked=false（保留按钮）。"""
    _patch_session_locals(monkeypatch, db_session)
    post_subs = [{"id": "p1", "name": "归档"}, {"id": "p2", "name": "更新题库"}]
    monkeypatch.setattr(
        "app.webhook.feishu_card.get_card_context",
        lambda msg_id: {"type": "post_confirm", "task_id": "t1", "post_subtasks": post_subs},
    )
    payload = _form_outside_payload("om_4b", "story4B_全不选", task_id="t1")
    resp = client.post(_WEBHOOK, json=payload)
    assert resp.status_code == 200
    assert resp.json()["toast"]["content"] == "已全不选"
    card = resp.json()["card"]["data"]
    # 卡片仍是 blue（非终态，保留按钮）
    assert card["header"]["template"] == "blue"
    # 所有 checker checked=false
    form = card["body"]["elements"][1]
    checkers = [e for e in form["elements"] if e.get("tag") == "checker"]
    assert len(checkers) == 2
    assert all(c["checked"] is False for c in checkers)


def test_s4b_select_all_retains_buttons(client, db_session, monkeypatch):
    """全选/全不选后卡片保留全选/全不选/确认按钮（不提交 form）。"""
    _patch_session_locals(monkeypatch, db_session)
    post_subs = [{"id": "p1", "name": "归档"}]
    monkeypatch.setattr(
        "app.webhook.feishu_card.get_card_context",
        lambda msg_id: {"type": "post_confirm", "task_id": "t1", "post_subtasks": post_subs},
    )
    payload = _form_outside_payload("om_4b", "story4B_全不选", task_id="t1")
    resp = client.post(_WEBHOOK, json=payload)
    assert resp.status_code == 200
    card = resp.json()["card"]["data"]
    form = card["body"]["elements"][1]
    # 确认按钮仍在
    buttons = [e for e in form["elements"] if e.get("tag") == "button"]
    assert any(b.get("name") == "confirm_btn" for b in buttons)
    # 全选/全不选 column_set 仍在
    col_sets = [e for e in form["elements"] if e.get("tag") == "column_set"]
    assert len(col_sets) == 1
