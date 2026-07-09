"""Story9 集成测试：board 编辑 + 状态变更 + 物理删除（API + DB）。

验收要点（doc/01 S9 + doc/04 §3.12）：
  - PUT /board/{entity}/{id}：字段编辑（name/description/deadline/executor）落库
  - PUT /board/phase/{id}：new_tasks 新增任务
  - PUT /board/theme/{id}：phase_orders 阶段排序
  - PUT managed/path 不可改（400）
  - POST /board/{entity}/{id}/status：pause（缺 reason 1005 / 填了成功）
  - POST /board/{entity}/{id}/status：resume（不填 reason）/ revert（填 reason + 级联）
  - POST /board/{entity}/{id}/status：forward 拒绝
  - DELETE /tasks/{id}：物理删除 + 关联记录清理
  - GET /workspaces/{id}：返回 managed/path
"""

from uuid import uuid4

from app.models.daily_task import DailyTask
from app.models.status_change_log import StatusChangeLog
from app.models.subtask import Subtask
from app.models.task import Task
from app.models.workspace import Workspace
from app.models.workspace_progress import WorkspaceProgress
from tests._factory import make_tree

_API = "/api/v1"


def _activate_tree(db_session, *, tasks_per_phase=1, n_themes=1, phases_per_theme=1):
    """建树 + 激活 phase/theme/goal，返回 (goal, themes, phases, tasks_by_phase)。"""
    goal, themes, phases = make_tree(
        db_session,
        n_themes=n_themes,
        phases_per_theme=phases_per_theme,
        tasks_per_phase=tasks_per_phase,
    )
    goal.status = "进行中"
    for theme in themes:
        theme.status = "进行中"
    for phase in phases:
        phase.status = "进行中"
    db_session.flush()

    tasks_by_phase = {}
    for phase in phases:
        tasks_by_phase[phase.id] = list(
            db_session.query(Task).filter(Task.phase_id == phase.id).order_by(Task.sort_order)
        )
    return goal, themes, phases, tasks_by_phase


def _complete_all(db_session, goal, themes, phases, tasks_by_phase):
    """完成所有 task -> 级联完成 phase/theme/goal。"""
    for phase_tasks in tasks_by_phase.values():
        for t in phase_tasks:
            t.status = "已完成"
            t.completed_at = None  # flush 后级联重算
    db_session.flush()
    first_task = list(tasks_by_phase.values())[0][0]
    from app.core import cascade

    cascade.cascade_status(db_session, "task", first_task.id)
    db_session.flush()


# ===== PUT /board/{entity}/{id} 字段编辑 =====


def test_put_board_phase_edit_fields(client, db_session):
    """PUT /board/phase/{id}：编辑 name + deadline，落库。"""
    goal, themes, phases, _ = _activate_tree(db_session)
    phase = phases[0]

    resp = client.put(
        f"{_API}/board/phase/{phase.id}",
        json={"fields": {"name": "新阶段名", "deadline": "2026-08-15"}},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["entity"] == "phase"
    assert data["id"] == phase.id
    assert set(data["updated_fields"]) == {"name", "deadline"}

    db_session.expire_all()
    assert phase.name == "新阶段名"
    assert str(phase.deadline) == "2026-08-15"


def test_put_board_task_edit_executor(client, db_session):
    """PUT /board/task/{id}：编辑 executor（单选 人/智能体）。"""
    goal, themes, phases, tasks_by_phase = _activate_tree(db_session)
    task = tasks_by_phase[phases[0].id][0]

    resp = client.put(
        f"{_API}/board/task/{task.id}",
        json={"fields": {"executor": "agent", "description": "新描述"}},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert set(data["updated_fields"]) == {"executor", "description"}

    db_session.expire_all()
    assert task.executor == "agent"
    assert task.description == "新描述"


def test_put_board_managed_not_editable(client, db_session):
    """PUT /board/theme/{id}：managed 不可改 -> 400。"""
    goal, themes, phases, _ = _activate_tree(db_session)

    resp = client.put(
        f"{_API}/board/theme/{themes[0].id}",
        json={"fields": {"managed": False}},
    )
    assert resp.status_code == 400


def test_put_board_goal_edit_name(client, db_session):
    """PUT /board/goal/{id}：编辑 name。"""
    goal, themes, phases, _ = _activate_tree(db_session)

    resp = client.put(
        f"{_API}/board/goal/{goal.id}",
        json={"fields": {"name": "新目标名"}},
    )
    assert resp.status_code == 200, resp.text
    db_session.expire_all()
    assert goal.name == "新目标名"


def test_put_board_invalid_entity_returns_400(client, db_session):
    """PUT /board/invalid/{id}：不支持的 entity -> 400。"""
    resp = client.put(
        f"{_API}/board/invalid/some-id",
        json={"fields": {"name": "x"}},
    )
    assert resp.status_code == 400


def test_put_board_not_found_returns_404(client, db_session):
    """PUT /board/phase/{id}：不存在的 entity -> 404。"""
    resp = client.put(
        f"{_API}/board/phase/no-such-id",
        json={"fields": {"name": "x"}},
    )
    assert resp.status_code == 404


# ===== PUT /board/phase/{id} new_tasks =====


def test_put_board_phase_new_tasks(client, db_session):
    """PUT /board/phase/{id}：new_tasks 新增任务，sort_order 自动分配。"""
    goal, themes, phases, tasks_by_phase = _activate_tree(db_session, tasks_per_phase=1)
    phase = phases[0]

    resp = client.put(
        f"{_API}/board/phase/{phase.id}",
        json={
            "fields": {
                "new_tasks": [
                    {"name": "新任务1", "executor": "human"},
                    {"name": "新任务2", "description": "描述"},
                ]
            }
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert "new_tasks" in data["updated_fields"]
    assert len(data["created_task_ids"]) == 2

    db_session.expire_all()
    new_tasks = (
        db_session.query(Task).filter(Task.phase_id == phase.id).order_by(Task.sort_order).all()
    )
    # 原有 1 个 + 新增 2 个
    assert len(new_tasks) == 3
    assert new_tasks[1].name == "新任务1"
    assert new_tasks[1].executor == "human"
    assert new_tasks[1].sort_order == 2
    assert new_tasks[2].name == "新任务2"
    assert new_tasks[2].sort_order == 3


# ===== PUT /board/theme/{id} phase_orders =====


def test_put_board_theme_phase_orders(client, db_session):
    """PUT /board/theme/{id}：phase_orders 阶段重排。"""
    goal, themes, phases, _ = _activate_tree(db_session, phases_per_theme=3)
    theme = themes[0]
    # 原始顺序: phase[0]=1, phase[1]=2, phase[2]=3
    # 重排: phase[2]=1, phase[0]=2, phase[1]=3
    resp = client.put(
        f"{_API}/board/theme/{theme.id}",
        json={
            "fields": {
                "phase_orders": [
                    {"phase_id": phases[2].id, "sort_order": 1},
                    {"phase_id": phases[0].id, "sort_order": 2},
                    {"phase_id": phases[1].id, "sort_order": 3},
                ]
            }
        },
    )
    assert resp.status_code == 200, resp.text
    assert "phase_orders" in resp.json()["data"]["updated_fields"]

    db_session.expire_all()
    assert phases[2].sort_order == 1
    assert phases[0].sort_order == 2
    assert phases[1].sort_order == 3


# ===== POST /board/{entity}/{id}/status =====


def test_post_board_status_pause_requires_reason(client, db_session):
    """POST /board/phase/{id}/status：pause 缺 reason -> 1005。"""
    goal, themes, phases, _ = _activate_tree(db_session)
    phase = phases[0]

    resp = client.post(
        f"{_API}/board/phase/{phase.id}/status",
        json={"to_status": "已暂停", "triggered_by": "user"},
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == 1005


def test_post_board_status_pause_success(client, db_session):
    """POST /board/phase/{id}/status：pause 填 reason -> 成功 + 不占名额。"""
    goal, themes, phases, _ = _activate_tree(db_session)
    phase = phases[0]

    resp = client.post(
        f"{_API}/board/phase/{phase.id}/status",
        json={"to_status": "已暂停", "reason": "等依赖", "triggered_by": "user"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["from_status"] == "进行中"
    assert data["to_status"] == "已暂停"
    assert data["change_type"] == "pause"
    assert data["audit_logged"] is True
    # pause 无级联
    assert data["cascade"]["phase_reverted"] is False

    db_session.expire_all()
    assert phase.status == "已暂停"
    assert phase.paused_at is not None
    # 审计
    assert db_session.query(StatusChangeLog).filter_by(change_type="pause").count() == 1


def test_post_board_status_resume_no_reason(client, db_session):
    """POST /board/phase/{id}/status：resume 不填 reason -> 成功 + 重新纳入。"""
    goal, themes, phases, _ = _activate_tree(db_session)
    phase = phases[0]
    phase.status = "已暂停"
    phase.paused_at = __import__("datetime").datetime.now()
    db_session.flush()

    resp = client.post(
        f"{_API}/board/phase/{phase.id}/status",
        json={"to_status": "进行中", "triggered_by": "user"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["change_type"] == "resume"

    db_session.expire_all()
    assert phase.status == "进行中"
    assert phase.paused_at is None


def test_post_board_status_task_revert_with_cascade(client, db_session):
    """POST /board/task/{id}/status：revert 填 reason + 级联拉回 phase/theme/goal。"""
    goal, themes, phases, tasks_by_phase = _activate_tree(db_session, tasks_per_phase=1)
    _complete_all(db_session, goal, themes, phases, tasks_by_phase)
    task = tasks_by_phase[phases[0].id][0]
    assert task.status == "已完成"
    assert phases[0].status == "已完成"

    resp = client.post(
        f"{_API}/board/task/{task.id}/status",
        json={"to_status": "待执行", "reason": "标记错了", "triggered_by": "user"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["change_type"] == "revert"
    assert data["cascade"]["phase_reverted"] is True
    assert data["cascade"]["theme_reverted"] is True
    assert data["cascade"]["goal_reverted"] is True
    assert data["cascade"]["phase_id"] == phases[0].id

    db_session.expire_all()
    assert task.status == "待执行"
    assert task.completed_at is None
    assert phases[0].status == "进行中"
    assert themes[0].status == "进行中"
    assert goal.status == "进行中"


def test_post_board_status_phase_revert_cascade(client, db_session):
    """POST /board/phase/{id}/status：phase revert + 级联拉回 theme/goal（不向下回退子 task）。"""
    goal, themes, phases, tasks_by_phase = _activate_tree(db_session, tasks_per_phase=2)
    _complete_all(db_session, goal, themes, phases, tasks_by_phase)
    phase = phases[0]
    assert phase.status == "已完成"

    resp = client.post(
        f"{_API}/board/phase/{phase.id}/status",
        json={"to_status": "进行中", "reason": "阶段回退", "triggered_by": "user"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["change_type"] == "revert"
    assert data["cascade"]["theme_reverted"] is True
    assert data["cascade"]["goal_reverted"] is True

    db_session.expire_all()
    assert phase.status == "进行中"
    assert themes[0].status == "进行中"
    assert goal.status == "进行中"
    # 子 task 完成态保留（不向下回退）
    for t in tasks_by_phase[phase.id]:
        assert t.status == "已完成"


def test_post_board_status_revert_requires_reason(client, db_session):
    """POST /board/task/{id}/status：revert 缺 reason -> 1005。"""
    goal, themes, phases, tasks_by_phase = _activate_tree(db_session, tasks_per_phase=1)
    _complete_all(db_session, goal, themes, phases, tasks_by_phase)
    task = tasks_by_phase[phases[0].id][0]

    resp = client.post(
        f"{_API}/board/task/{task.id}/status",
        json={"to_status": "待执行", "triggered_by": "user"},
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == 1005


def test_post_board_status_forward_rejected(client, db_session):
    """POST /board/phase/{id}/status：forward（未开始->进行中）-> 400（board 不提供 forward）。"""
    goal, themes, phases = make_tree(db_session, phases_per_theme=1, tasks_per_phase=0)
    db_session.flush()
    phase = phases[0]
    assert phase.status == "未开始"

    resp = client.post(
        f"{_API}/board/phase/{phase.id}/status",
        json={"to_status": "进行中", "triggered_by": "user"},
    )
    assert resp.status_code == 400
    assert "forward" in resp.json()["message"].lower() or "activate" in resp.json()["message"]


def test_post_board_status_theme_pause_resume(client, db_session):
    """POST /board/theme/{id}/status：theme pause + resume（S9 扩展）。"""
    goal, themes, phases, _ = _activate_tree(db_session)

    # pause
    resp = client.post(
        f"{_API}/board/theme/{themes[0].id}/status",
        json={"to_status": "已暂停", "reason": "专题暂停", "triggered_by": "user"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["change_type"] == "pause"

    db_session.expire_all()
    assert themes[0].status == "已暂停"

    # resume
    resp = client.post(
        f"{_API}/board/theme/{themes[0].id}/status",
        json={"to_status": "进行中", "triggered_by": "user"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["change_type"] == "resume"

    db_session.expire_all()
    assert themes[0].status == "进行中"


def test_post_board_status_goal_revert_no_cascade(client, db_session):
    """POST /board/goal/{id}/status：goal revert 填 reason + 无级联（无上级）。"""
    goal, themes, phases, tasks_by_phase = _activate_tree(db_session, tasks_per_phase=1)
    _complete_all(db_session, goal, themes, phases, tasks_by_phase)
    assert goal.status == "已完成"

    resp = client.post(
        f"{_API}/board/goal/{goal.id}/status",
        json={"to_status": "进行中", "reason": "目标回退", "triggered_by": "user"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["change_type"] == "revert"
    assert data["cascade"]["phase_reverted"] is False
    assert data["cascade"]["theme_reverted"] is False
    assert data["cascade"]["goal_reverted"] is False

    db_session.expire_all()
    assert goal.status == "进行中"


def test_post_board_status_not_found(client, db_session):
    """POST /board/phase/{id}/status：不存在 -> 404。"""
    resp = client.post(
        f"{_API}/board/phase/no-such-id/status",
        json={"to_status": "已暂停", "reason": "x"},
    )
    assert resp.status_code == 404


# ===== DELETE /tasks/{taskId} =====


def test_delete_task_physical_delete(client, db_session):
    """DELETE /tasks/{id}：物理删除 + 关联记录清理。"""
    goal, themes, phases, tasks_by_phase = _activate_tree(db_session, tasks_per_phase=1)
    task = tasks_by_phase[phases[0].id][0]

    # 添加关联记录
    from datetime import date

    from app.models.daily_record import DailyRecord

    daily = DailyRecord(
        id=str(uuid4()),
        date=date(2026, 7, 9),
        week="2026-W28",
        push_source="manual",
    )
    db_session.add(daily)
    db_session.flush()
    dt = DailyTask(id=str(uuid4()), daily_id=daily.id, task_id=task.id)
    db_session.add(dt)
    sub = Subtask(
        id=str(uuid4()),
        task_id=task.id,
        sort_order=1,
        name="前置1",
        type="前置",
        status="待执行",
    )
    db_session.add(sub)
    # 需要真实 workspace（FK 约束）
    ws = Workspace(
        id=str(uuid4()),
        theme_id=themes[0].id,
        path="/tmp/test",
        managed=True,
        status="已就绪",
        type="learning",
    )
    db_session.add(ws)
    db_session.flush()
    wp = WorkspaceProgress(
        id=str(uuid4()),
        workspace_id=ws.id,
        date=date(2026, 7, 9),
        task_id=task.id,
        file_path="/tmp/x.md",
        file_type="note",
    )
    db_session.add(wp)
    db_session.flush()

    resp = client.delete(f"{_API}/tasks/{task.id}")
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["task_id"] == task.id
    assert data["deleted"] is True

    # DB 验证：task + 关联记录都删了
    db_session.expire_all()
    assert db_session.query(Task).filter_by(id=task.id).first() is None
    assert db_session.query(DailyTask).filter_by(task_id=task.id).count() == 0
    assert db_session.query(Subtask).filter_by(task_id=task.id).count() == 0
    assert db_session.query(WorkspaceProgress).filter_by(task_id=task.id).count() == 0


def test_delete_task_not_found(client, db_session):
    """DELETE /tasks/{id}：不存在 -> 404。"""
    resp = client.delete(f"{_API}/tasks/no-such-id")
    assert resp.status_code == 404


# ===== GET /workspaces/{id} =====


def test_get_workspace_returns_managed_path(client, db_session):
    """GET /workspaces/{id}：返回 managed/path（H5 只读查看，doc/01 S9 场景7）。"""
    goal, themes, phases = make_tree(db_session, tasks_per_phase=0)
    db_session.flush()
    ws = Workspace(
        id=str(uuid4()),
        theme_id=themes[0].id,
        path="/Users/me/project",
        managed=True,
        status="已就绪",
        type="learning",
    )
    db_session.add(ws)
    db_session.flush()

    resp = client.get(f"{_API}/workspaces/{ws.id}")
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["managed"] is True
    assert data["path"] == "/Users/me/project"
    assert data["status"] == "已就绪"
    assert data["type"] == "learning"


def test_get_workspace_not_found(client, db_session):
    """GET /workspaces/{id}：不存在 -> 404。"""
    resp = client.get(f"{_API}/workspaces/no-such-id")
    assert resp.status_code == 404
