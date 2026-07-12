"""PR-D1 集成测试：btn_name 路由 + form_value 4 类型解析 + card_registry 反查 + reassign 互斥。

覆盖 doc/09 V7（form_value 类型）+ V8（form_submit 靠 name 路由）+ V2（message_id 路径）。

测试矩阵：
  - checker（bool）：S3 候选任务/前置、S4B 后置、S5 任务状态对比反转、S4A场景4 确认完成
  - date_picker（日期字符串含时区）：S2 卡片B deadline、S8 阶段衔接 deadline
  - input（字符串）：S4A feedback（issue#20）
  - card_registry 反查：None 容错、type 分发、各类型上下文
  - S4A场景4 reassign 互斥：reassign=true 不走确认完成
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
from app.services.task_app_svc import TaskAppSvc
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
    assert resp.json()["code"] == 0

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
    assert resp.json()["data"]["post_subtask_count"] == 1


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
    assert resp.json()["code"] == 0

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
    assert resp.json()["data"]["action"] == "retry"
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


# ===== S4A 场景4 reassign 互斥（doc/09 §S4A 实现注意）=====


def test_reassign_mutual_exclusion(client, db_session, monkeypatch):
    """task_<id>_reassign=true -> 不走确认完成，走 reassign（改 executor=agent + 下发）。

    doc/09 §S4A 场景4 实现注意：reassign checker 勾选后，该 task 不走"确认完成"，
    而是"改 executor=agent + 重新下发"（同一 task 不能既确认完成又重新下发）。
    """
    from tests.integration.test_story4a_agent import _make_full_tree

    goal, themes, phases, ws, tasks = _make_full_tree(db_session)
    task1, task2 = tasks[0], tasks[1]
    db_session.flush()

    monkeypatch.setattr(
        "app.webhook.feishu_card.get_card_context",
        lambda msg_id: {"type": "task_complete", "workspace_id": ws.id},
    )
    # mock reassign 的 opencode 调用
    with (
        patch.object(task_app_svc.TaskAppSvc, "confirm_complete") as mock_complete,
        patch.object(task_app_svc.TaskAppSvc, "reassign_to_agent") as mock_reassign,
    ):
        mock_complete.return_value = {"task_id": task2.id, "status": "已完成"}
        mock_reassign.return_value = {"task_id": task1.id, "executor": "agent", "reassigned": True}
        payload = _form_submit_payload(
            "om_tc",
            "confirm_btn",
            {
                f"task_{task1.id}_reassign": True,  # reassign -> 不走确认完成
                f"task_{task2.id}": True,  # 确认完成
            },
        )
        resp = client.post(_WEBHOOK, json=payload)

    assert resp.status_code == 200, resp.text
    results = resp.json()["data"]["results"]
    actions = {r["task_id"]: r["action"] for r in results}
    assert actions[task1.id] == "reassigned"
    assert actions[task2.id] == "completed"
    # confirm_complete 只对 task2 调用（不含 task1）
    mock_complete.assert_called_once_with(task2.id, "feishu_user")
    # reassign 只对 task1 调用
    mock_reassign.assert_called_once_with(task1.id, "feishu_user")


def test_reassign_only(client, db_session, monkeypatch):
    """只有 reassign，无确认完成。"""
    from tests.integration.test_story4a_agent import _make_full_tree

    goal, themes, phases, ws, tasks = _make_full_tree(db_session)
    task1 = tasks[0]
    db_session.flush()

    monkeypatch.setattr(
        "app.webhook.feishu_card.get_card_context",
        lambda msg_id: {"type": "task_complete", "workspace_id": ws.id},
    )
    with (
        patch.object(task_app_svc.TaskAppSvc, "confirm_complete") as mock_complete,
        patch.object(task_app_svc.TaskAppSvc, "reassign_to_agent") as mock_reassign,
    ):
        mock_reassign.return_value = {"task_id": task1.id, "executor": "agent", "reassigned": True}
        payload = _form_submit_payload(
            "om_tc",
            "confirm_btn",
            {f"task_{task1.id}_reassign": True, f"task_{task1.id}": True},
        )
        resp = client.post(_WEBHOOK, json=payload)

    assert resp.status_code == 200
    results = resp.json()["data"]["results"]
    assert len(results) == 1
    assert results[0]["action"] == "reassigned"
    mock_complete.assert_not_called()


def test_reassign_to_agent_changes_executor(client, db_session):
    """reassign_to_agent -> task.executor 改为 'agent'。"""
    from tests.integration.test_story4a_agent import _make_full_tree

    goal, themes, phases, ws, tasks = _make_full_tree(db_session)
    task = tasks[0]
    task.executor = "human"
    db_session.flush()

    with patch.object(task_app_svc.OpenCodeClient, "start_agent_serve", return_value=18800):
        result = TaskAppSvc(db_session).reassign_to_agent(task.id)

    db_session.refresh(task)
    assert task.executor == "agent"
    assert result["reassigned"] is True
