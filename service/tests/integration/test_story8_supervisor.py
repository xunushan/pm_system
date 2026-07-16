"""Story8 集成测试：阶段衔接激活 + webhook + 事件端到端。

验收要点（doc/01 S8）：
  - POST /schedules/activate: 激活+即时级联+审计(forward,supervisor)+workspace
  - 全局进行中 <= 3（≤3 校验）
  - 同专题已有进行中 -> 409
  - webhook story8_确认激活/暂不激活/去激活/去页面调整
  - 事件端到端：task 完成 -> cascade emit phase_completed
  - 事件不阻塞事务（3 秒内返回）
  - 周统计 supervisor_linking_status 真查询
"""

import time
from datetime import date
from uuid import uuid4

from app.models.status_change_log import StatusChangeLog
from app.models.task import Task
from app.models.workspace import Workspace
from app.services.stats_app_svc import StatsAppSvc
from app.services.task_app_svc import TaskAppSvc
from app.supervisor import event_bus
from app.supervisor.event_bus import dispatch_sync, set_dispatch_func
from tests._factory import make_tree

_API = "/api/v1"
_WEBHOOK = "/webhook/feishu/card"


def _drain_queue():
    """清空事件队列（Queue 无 clear 方法，逐个 get）。"""
    while not event_bus._queue.empty():
        try:
            event_bus._queue.get_nowait()
        except Exception:  # noqa: BLE001
            break


class FakeFeishu:
    def __init__(self):
        self.cards = []

    def send_card(self, chat_id, card):
        self.cards.append(card)


# ---- POST /schedules/activate ----


def test_activate_full_flow(client, db_session):
    """阶段衔接激活：phase 进行中 + 级联 + 审计(forward,supervisor) + workspace。"""
    goal, themes, phases = make_tree(db_session, n_themes=1, phases_per_theme=2)
    # 首阶段已完成，第二阶段未开始
    phases[0].status = "已完成"
    phases[0].activated_at = date(2026, 7, 1)
    goal.status = "进行中"
    themes[0].status = "进行中"
    db_session.flush()

    body = {"phase_id": phases[1].id, "deadline": "2026-07-25", "user_id": "supervisor"}
    resp = client.post(f"{_API}/schedules/activate", json=body)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["phase_id"] == phases[1].id
    assert data["status"] == "进行中"
    assert data["deadline"] == "2026-07-25"
    assert data["workspace_id"]  # 复用/创建 workspace

    # DB: phase 已激活
    db_session.expire_all()
    assert phases[1].status == "进行中"
    assert phases[1].activated_at is not None
    # 审计：forward + triggered_by='supervisor'
    log = (
        db_session.query(StatusChangeLog)
        .filter_by(entity_type="phase", entity_id=phases[1].id, change_type="forward")
        .first()
    )
    assert log is not None
    assert log.triggered_by == "supervisor"


def test_activate_reuses_existing_workspace(client, db_session):
    """主题已有 workspace（S2 创建）-> 复用，不新建。"""
    goal, themes, phases = make_tree(db_session, n_themes=1, phases_per_theme=2)
    phases[0].status = "已完成"
    phases[0].activated_at = date(2026, 7, 1)
    # 已有 workspace
    ws = Workspace(
        id=str(uuid4()),
        theme_id=themes[0].id,
        path="data/workspaces/existing",
        managed=True,
        status="已就绪",
        type="learning",
    )
    db_session.add(ws)
    goal.status = "进行中"
    themes[0].status = "进行中"
    db_session.flush()

    body = {"phase_id": phases[1].id, "deadline": "2026-07-25"}
    resp = client.post(f"{_API}/schedules/activate", json=body)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["workspace_id"] == ws.id  # 复用
    assert data["workspace_status"] == "已就绪"
    # 不新建 workspace
    assert db_session.query(Workspace).count() == 1


def test_activate_quota_exceeded(client, db_session):
    """全局进行中 >= 3 -> 409(1004)。"""
    goal, themes, phases = make_tree(db_session, n_themes=4, phases_per_theme=2)
    for i in range(3):
        phases[i].status = "进行中"
    db_session.flush()

    body = {"phase_id": phases[3].id, "deadline": "2026-07-25"}
    resp = client.post(f"{_API}/schedules/activate", json=body)
    assert resp.status_code == 409
    assert resp.json()["code"] == 1004


def test_activate_same_theme_has_active(client, db_session):
    """同专题已有进行中 phase -> 409。"""
    goal, themes, phases = make_tree(db_session, n_themes=1, phases_per_theme=2)
    phases[0].status = "进行中"  # 同专题已有进行中
    db_session.flush()

    body = {"phase_id": phases[1].id, "deadline": "2026-07-25"}
    resp = client.post(f"{_API}/schedules/activate", json=body)
    assert resp.status_code == 409
    assert resp.json()["code"] == 1003


def test_activate_wrong_status(client, db_session):
    """phase 非 '未开始' -> 409。"""
    goal, themes, phases = make_tree(db_session, n_themes=1, phases_per_theme=2)
    phases[1].status = "已暂停"
    db_session.flush()

    body = {"phase_id": phases[1].id, "deadline": "2026-07-25"}
    resp = client.post(f"{_API}/schedules/activate", json=body)
    assert resp.status_code == 409


def test_activate_not_found(client, db_session):
    """phase 不存在 -> 404。"""
    body = {"phase_id": "nonexistent", "deadline": "2026-07-25"}
    resp = client.post(f"{_API}/schedules/activate", json=body)
    assert resp.status_code == 404


# ---- webhook story8 ----


def test_webhook_story8_confirm_activate(client, db_session, monkeypatch):
    """btn_activate (phase_linking) -> 调度激活服务 + 即时级联。

    deadline 从 form_value.deadline 解析（date_picker，doc/09 V7）。
    phase_id 靠 message_id 反查 card_registry（type=phase_linking）。
    """
    goal, themes, phases = make_tree(db_session, n_themes=1, phases_per_theme=2)
    phases[0].status = "已完成"
    goal.status = "进行中"
    themes[0].status = "进行中"
    db_session.flush()

    monkeypatch.setattr(
        "app.webhook.feishu_card.get_card_context",
        lambda msg_id: {"type": "phase_linking", "phase_id": phases[1].id},
    )

    payload = {
        "event": {
            "context": {"open_message_id": "om_test"},
            "action": {
                "name": "btn_activate",
                "form_value": {"deadline": "2026-07-25 +0800"},
            },
        }
    }
    resp = client.post(_WEBHOOK, json=payload)
    assert resp.status_code == 200
    # 方案 B：同步返回 toast + card（已激活态）
    assert resp.json()["toast"]["content"] == "已激活"

    db_session.expire_all()
    assert phases[1].status == "进行中"


def test_webhook_story8_skip_activate(client, db_session, monkeypatch):
    """btn_defer (phase_linking) -> no-op（不激活）。"""
    goal, themes, phases = make_tree(db_session, n_themes=1, phases_per_theme=2)
    db_session.flush()

    monkeypatch.setattr(
        "app.webhook.feishu_card.get_card_context",
        lambda msg_id: {"type": "phase_linking", "phase_id": phases[1].id},
    )

    payload = {
        "event": {
            "context": {"open_message_id": "om_test"},
            "action": {"name": "btn_defer", "form_value": {}},
        }
    }
    resp = client.post(_WEBHOOK, json=payload)
    assert resp.status_code == 200
    # 方案 B：同步返回 toast + card（已暂缓态）
    assert resp.json()["toast"]["content"] == "已暂缓"
    # phase 状态不变
    db_session.expire_all()
    assert phases[1].status == "未开始"


def test_webhook_story8_go_activate(client, db_session):
    """story8_去激活 -> 返回链接（跳转，非事务）。"""
    payload = {
        "event": {
            "context": {"open_message_id": "om_test"},
            "action": {
                "value": {
                    "action_id": "story8_去激活",
                    "goal_id": "g1",
                    "theme_id": "t1",
                    "user_id": "u1",
                }
            },
        }
    }
    resp = client.post(_WEBHOOK, json=payload)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "link" in data
    assert "schedule" in data["link"]


def test_webhook_story8_go_page(client, db_session):
    """story8_去页面调整 -> 返回 H5 链接。"""
    payload = {
        "event": {
            "context": {"open_message_id": "om_test"},
            "action": {
                "value": {
                    "action_id": "story8_去页面调整",
                    "phase_id": "p1",
                    "user_id": "u1",
                }
            },
        }
    }
    resp = client.post(_WEBHOOK, json=payload)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "link" in data
    assert "board" in data["link"]


# ---- 事件端到端 ----


def test_event_end_to_end_task_complete_emit_phase_completed(db_session):
    """task 完成 -> cascade emit phase_completed -> 事件在队列中。"""
    goal, themes, phases = make_tree(db_session, n_themes=1, phases_per_theme=1, tasks_per_phase=1)
    phases[0].status = "进行中"
    phases[0].activated_at = date(2026, 7, 1)
    goal.status = "进行中"
    themes[0].status = "进行中"
    db_session.flush()

    task = db_session.query(Task).filter_by(phase_id=phases[0].id).first()

    # 清空队列
    _drain_queue()

    # 完成任务 -> cascade -> emit
    TaskAppSvc(db_session).complete(task.id, "u1")

    # phase 应已完成
    db_session.expire_all()
    assert phases[0].status == "已完成"

    # 队列中应有 phase_completed 事件
    events = []
    while not event_bus._queue.empty():
        try:
            events.append(event_bus._queue.get_nowait())
        except Exception:  # noqa: BLE001
            break
    types = [e["type"] for e in events]
    assert "phase_completed" in types

    phase_events = [e for e in events if e["type"] == "phase_completed"]
    assert phase_events[0]["entity_id"] == phases[0].id


def test_event_dispatch_sync_routes_to_handler(db_session, monkeypatch):
    """dispatch_sync 路由 phase_completed -> on_phase_completed（mock handler）。"""
    called = []
    monkeypatch.setattr(
        "app.supervisor.handlers.on_phase_completed", lambda pid: called.append(pid)
    )

    # 恢复默认分发（conftest 设了 no-op）
    set_dispatch_func(None)
    try:
        dispatch_sync({"type": "phase_completed", "entity_id": "phase_001"})
        assert called == ["phase_001"]
    finally:
        set_dispatch_func(lambda _e: None)


def test_event_does_not_block_transaction(db_session):
    """emit 在事务内调用 -> 事务正常 commit，快速返回。"""
    goal, themes, phases = make_tree(db_session, n_themes=1, phases_per_theme=1, tasks_per_phase=1)
    phases[0].status = "进行中"
    phases[0].activated_at = date(2026, 7, 1)
    goal.status = "进行中"
    themes[0].status = "进行中"
    db_session.flush()

    task = db_session.query(Task).filter_by(phase_id=phases[0].id).first()
    _drain_queue()

    # 计时
    start = time.monotonic()
    TaskAppSvc(db_session).complete(task.id, "u1")
    elapsed = time.monotonic() - start

    # 事务在 3 秒内完成（emit 入队不阻塞）
    assert elapsed < 3.0
    # 事件已入队（emit 被调用）
    assert event_bus._queue.qsize() > 0
    # 清理队列
    _drain_queue()


# ---- 周统计 supervisor_linking_status 真查询 ----


def test_weekly_stats_linking_status_with_next_phase(db_session):
    """有进行中阶段且有下一阶段 -> supervisor_linking_status 返回 next_phase。"""
    goal, themes, phases = make_tree(db_session, n_themes=1, phases_per_theme=2, tasks_per_phase=1)
    goal.status = "进行中"
    themes[0].status = "进行中"
    phases[0].status = "进行中"
    phases[0].activated_at = date(2026, 7, 1)
    db_session.flush()

    data = StatsAppSvc(db_session).get_weekly_stats("u1", "2026-W28")
    assert data.supervisor_linking_status is not None
    assert data.supervisor_linking_status.next_phase == phases[1].id
    assert data.supervisor_linking_status.suggested_deadline is not None


def test_weekly_stats_linking_status_no_next_phase(db_session):
    """进行中阶段是最后一个 -> next_phase=None。"""
    goal, themes, phases = make_tree(db_session, n_themes=1, phases_per_theme=1, tasks_per_phase=1)
    goal.status = "进行中"
    themes[0].status = "进行中"
    phases[0].status = "进行中"
    phases[0].activated_at = date(2026, 7, 1)
    db_session.flush()

    data = StatsAppSvc(db_session).get_weekly_stats("u1", "2026-W28")
    assert data.supervisor_linking_status.next_phase is None


def test_weekly_stats_linking_status_no_active(db_session):
    """无进行中阶段 -> next_phase=None。"""
    goal, themes, phases = make_tree(db_session, n_themes=1, phases_per_theme=2)
    db_session.flush()

    data = StatsAppSvc(db_session).get_weekly_stats("u1", "2026-W28")
    assert data.supervisor_linking_status.next_phase is None
