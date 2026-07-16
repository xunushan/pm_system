"""PR-D1 集成测试：btn_name 路由 + form_value 4 类型解析 + card_registry 反查。

覆盖 doc/09 V7（form_value 类型）+ V8（form_submit 靠 name 路由）+ V2（message_id 路径）。

测试矩阵：
  - checker（bool）：S3 候选任务/前置、S4B 后置、S5 任务状态对比反转、S4A场景4 确认完成
  - date_picker（日期字符串含时区）：S2 卡片B deadline、S8 阶段衔接 deadline
  - input（字符串）：S4A feedback（issue#20）
  - card_registry 反查：None 容错、type 分发、各类型上下文
"""

from datetime import date
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy.orm import sessionmaker

from app.models.daily_record import DailyRecord
from app.models.daily_task import DailyTask
from app.models.phase import Phase
from app.models.subtask import Subtask
from app.models.task import Task
from app.services import daily_app_svc, task_app_svc
from tests._factory import make_tree

_WEBHOOK = "/webhook/feishu/card"
_TODAY = date(2026, 7, 6)


def _form_submit_payload(message_id, btn_name, form_value):
    """构造 schema 2.0 form_submit 回调 payload。"""
    return {
        "event": {
            "context": {"open_message_id": message_id},
            "action": {
                "name": btn_name,
                "form_value": form_value,
            },
        }
    }


# ===== checker form_value 解析（bool）=====


def test_checker_parse_s3_task_and_pre(client, db_session, monkeypatch):
    """S3 checker：task_<id>=true（选中今日要做）+ pre_<id>=true（选中前置）。"""
    goal, themes, phases = make_tree(db_session, n_themes=1, phases_per_theme=1, tasks_per_phase=2)
    phases[0].status = "进行中"
    phases[0].activated_at = _TODAY
    db_session.flush()

    tasks = list(db_session.query(Task).filter_by(phase_id=phases[0].id))
    db_session.flush()

    monkeypatch.setattr(
        daily_app_svc,
        "SessionLocal",
        sessionmaker(bind=db_session.bind, expire_on_commit=False),
    )
    pre_id = "pre-abc"
    monkeypatch.setattr(
        "app.webhook.feishu_card.get_card_context",
        lambda msg_id: {
            "type": "daily_plan",
            "date": "2026-07-06",
            "prerequisites": [{"id": pre_id, "name": "准备环境"}],
        },
    )

    # task_0=true, task_1=false, pre_abc=true
    payload = _form_submit_payload(
        "om_s3",
        "confirm_btn",
        {f"task_{tasks[0].id}": True, f"task_{tasks[1].id}": False, f"pre_{pre_id}": True},
    )
    resp = client.post(_WEBHOOK, json=payload)
    assert resp.status_code == 200, resp.text
    # 方案 B：同步返回 toast + card
    assert resp.json()["toast"]["content"] == "今日计划已确认"

    # 只勾选了 task_0
    assert db_session.query(DailyTask).count() == 1
    dt = db_session.query(DailyTask).one()
    assert dt.task_id == tasks[0].id
    # 前置插入 1 条
    assert db_session.query(Subtask).filter_by(type="前置").count() == 1


def test_checker_parse_s4b_post(client, db_session, monkeypatch):
    """S4B checker：post_<id>=true（勾选=要执行后置）。"""
    from tests.integration.test_story4b_tasks import _activate_and_get_task

    goal, themes, phases, task = _activate_and_get_task(db_session)
    task.status = "已完成"
    db_session.flush()

    monkeypatch.setattr(
        task_app_svc,
        "SessionLocal",
        sessionmaker(bind=db_session.bind, expire_on_commit=False),
    )
    p1, p2 = "post-1", "post-2"
    monkeypatch.setattr(
        "app.webhook.feishu_card.get_card_context",
        lambda msg_id: {
            "type": "post_confirm",
            "task_id": task.id,
            "post_subtasks": [
                {"id": p1, "name": "归档"},
                {"id": p2, "name": "更新题库"},
            ],
        },
    )
    with patch.object(task_app_svc.OpenCodeClient, "dispatch_post_subtasks"):
        payload = _form_submit_payload(
            "om_4b", "confirm_btn", {f"post_{p1}": True, f"post_{p2}": False}
        )
        resp = client.post(_WEBHOOK, json=payload)

    assert resp.status_code == 200
    # 方案 B：同步返回 toast + card（post_subtask_count=1 -> 有后置）
    assert resp.json()["toast"]["content"] == "已确认后置"
    card = resp.json()["card"]["data"]
    assert card["header"]["template"] == "green"
    assert "后置已确认" in card["body"]["elements"][0]["content"]


def test_checker_parse_s5_status_revert(client, db_session, monkeypatch):
    """S5 checker：已完成任务取消勾选 -> revert（true->false 标记未完成）。"""
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

    monkeypatch.setattr(
        daily_app_svc,
        "SessionLocal",
        sessionmaker(bind=db_session.bind, expire_on_commit=False),
    )
    monkeypatch.setattr(
        "app.webhook.feishu_card.get_card_context",
        lambda msg_id: {"type": "daily_summary", "daily_id": daily.id},
    )
    with patch.object(daily_app_svc, "write_daily_md"):
        # 已完成 -> 取消勾选（false）-> revert
        payload = _form_submit_payload("om_s5", "confirm_btn", {f"task_{task.id}": False})
        resp = client.post(_WEBHOOK, json=payload)

    assert resp.status_code == 200, resp.text
    db_session.flush()
    assert task.status == "待执行"
    assert daily.is_confirmed is True


# ===== date_picker form_value 解析（日期字符串含时区）=====


def test_date_picker_parse_s2_deadline(client, db_session, monkeypatch):
    """S2 date_picker：dl_theme_<id>="2026-07-15 +0800" -> 解析取日期部分。"""
    goal, themes, _ = make_tree(db_session)
    db_session.flush()

    monkeypatch.setattr(
        "app.webhook.feishu_card.get_card_context",
        lambda msg_id: {"type": "schedule_b", "goal_id": goal.id},
    )
    payload = _form_submit_payload(
        "om_s2b",
        "confirm_btn",
        {f"dl_theme_{themes[0].id}": "2026-07-15 +0800"},
    )
    resp = client.post(_WEBHOOK, json=payload)
    assert resp.status_code == 200, resp.text
    # 方案 B：同步返回 toast + card
    assert resp.json()["toast"]["content"] == "调度已确认"

    phase = db_session.query(Phase).filter_by(status="进行中").one()
    assert phase.deadline == date(2026, 7, 15)


def test_date_picker_parse_s8_deadline(client, db_session, monkeypatch):
    """S8 date_picker：deadline="2026-07-25 +0800" -> 解析取日期部分。"""
    goal, themes, phases = make_tree(db_session, n_themes=1, phases_per_theme=2)
    phases[0].status = "已完成"
    goal.status = "进行中"
    themes[0].status = "进行中"
    db_session.flush()

    monkeypatch.setattr(
        "app.webhook.feishu_card.get_card_context",
        lambda msg_id: {"type": "phase_linking", "phase_id": phases[1].id},
    )
    payload = _form_submit_payload("om_s8", "btn_activate", {"deadline": "2026-07-25 +0800"})
    resp = client.post(_WEBHOOK, json=payload)
    assert resp.status_code == 200
    db_session.expire_all()
    assert phases[1].status == "进行中"
    assert phases[1].deadline == date(2026, 7, 25)


def test_date_picker_invalid_format(client, db_session, monkeypatch):
    """date_picker 值格式无效 -> 1002。"""
    goal, themes, _ = make_tree(db_session)
    db_session.flush()

    monkeypatch.setattr(
        "app.webhook.feishu_card.get_card_context",
        lambda msg_id: {"type": "schedule_b", "goal_id": goal.id},
    )
    payload = _form_submit_payload(
        "om_s2b",
        "confirm_btn",
        {f"dl_theme_{themes[0].id}": "invalid-date"},
    )
    resp = client.post(_WEBHOOK, json=payload)
    assert resp.status_code == 200
    assert resp.json()["code"] == 1002


# ===== input form_value 解析（字符串）=====


def test_input_parse_s4a_feedback(client, db_session, monkeypatch):
    """S4A input：form_value.feedback="加一个大纲" -> output_reject 收到 feedback（issue#20）。"""
    from app.models.agent_process import AgentProcess
    from tests.integration.test_story4a_agent import _make_full_tree

    goal, themes, phases, ws, tasks = _make_full_tree(db_session)
    task = tasks[0]
    task.retry_count = 0
    ap = AgentProcess(id=str(uuid4()), workspace_id=ws.id, port=10001, status="running")
    db_session.add(ap)
    db_session.flush()

    monkeypatch.setattr(
        "app.webhook.feishu_card.get_card_context",
        lambda msg_id: {"type": "verification", "task_id": task.id},
    )
    feedback_text = "加一个大纲和代码注释"
    with (
        patch.object(task_app_svc.OpenCodeClient, "dispatch_task"),
        patch.object(task_app_svc, "set_task_timeout"),
    ):
        payload = _form_submit_payload("om_4a", "btn_reject", {"feedback": feedback_text})
        resp = client.post(_WEBHOOK, json=payload)

    assert resp.status_code == 200, resp.text
    # 方案 B：retry 路径同步返回 toast + card（橙色反馈已下发态）
    assert resp.json()["toast"]["content"] == "已下发修改"
    assert task.retry_count == 1


def test_input_empty_feedback_returns_1002(client, db_session, monkeypatch):
    """S4A btn_reject 缺 feedback -> 1002。"""
    monkeypatch.setattr(
        "app.webhook.feishu_card.get_card_context",
        lambda msg_id: {"type": "verification", "task_id": "t1"},
    )
    payload = _form_submit_payload("om_4a", "btn_reject", {"feedback": ""})
    resp = client.post(_WEBHOOK, json=payload)
    assert resp.status_code == 200
    assert resp.json()["code"] == 1002


# ===== card_registry 反查 =====


def test_card_registry_none_btn_pass(client, db_session, monkeypatch):
    """btn_pass card_registry None -> 1002（容错，不崩）。"""
    monkeypatch.setattr(
        "app.webhook.feishu_card.get_card_context",
        lambda msg_id: None,
    )
    payload = _form_submit_payload("om_x", "btn_pass", {})
    resp = client.post(_WEBHOOK, json=payload)
    assert resp.status_code == 200
    assert resp.json()["code"] == 1002


def test_card_registry_none_confirm_btn(client, db_session, monkeypatch):
    """confirm_btn card_registry None -> 1002（容错，不崩）。"""
    monkeypatch.setattr(
        "app.webhook.feishu_card.get_card_context",
        lambda msg_id: None,
    )
    payload = _form_submit_payload("om_x", "confirm_btn", {})
    resp = client.post(_WEBHOOK, json=payload)
    assert resp.status_code == 200
    assert resp.json()["code"] == 1002


def test_card_registry_unknown_type_confirm_btn(client, db_session, monkeypatch):
    """confirm_btn card_registry type 未知 -> 1002。"""
    monkeypatch.setattr(
        "app.webhook.feishu_card.get_card_context",
        lambda msg_id: {"type": "unknown_type"},
    )
    payload = _form_submit_payload("om_x", "confirm_btn", {})
    resp = client.post(_WEBHOOK, json=payload)
    assert resp.status_code == 200
    assert resp.json()["code"] == 1002
