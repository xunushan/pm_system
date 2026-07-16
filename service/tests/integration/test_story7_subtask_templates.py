"""Story7 集成测试：子任务模板 CRUD API + 合并查询（API + DB）。

验收要点（doc/01 S7 / doc/04 §3.10）：
  - GET /subtask-templates：按 scope_type/scope_id/type/status 过滤 + task_id 合并查询
  - POST /subtask-templates：创建成功 + UNIQUE 冲突 -> 3001
  - PUT /subtask-templates/{id}：更新成功 + name 冲突 3001 + status 切换
  - DELETE /subtask-templates/{id}：标记 inactive（非物理删除，可恢复，幂等）
  - 配置不校验专题 type（智能体专题配也能存）
"""

from uuid import uuid4

from app.models.subtask_template import SubtaskTemplate
from app.models.task import Task
from tests._factory import make_tree

_API = "/api/v1/subtask-templates"


def _add_template(
    db,
    *,
    scope_type="phase",
    scope_id=None,
    type="前置",
    name="模板",
    description=None,
    status="active",
):
    t = SubtaskTemplate(
        id=str(uuid4()),
        scope_type=scope_type,
        scope_id=scope_id or str(uuid4()),
        type=type,
        name=name,
        description=description,
        status=status,
    )
    db.add(t)
    db.flush()
    return t


# ===== GET /subtask-templates =====


def test_list_no_filter(client, db_session):
    """GET 无过滤：返回全部模板。"""
    for i in range(3):
        _add_template(db_session, name=f"模板{i}")
    resp = client.get(_API)
    assert resp.status_code == 200
    assert len(resp.json()["data"]["templates"]) == 3


def test_list_with_scope_filter(client, db_session):
    """GET 按 scope_type + scope_id 过滤。"""
    phase_id = str(uuid4())
    theme_id = str(uuid4())
    _add_template(db_session, scope_type="phase", scope_id=phase_id, name="A")
    _add_template(db_session, scope_type="theme", scope_id=theme_id, name="B")

    resp = client.get(_API, params={"scope_type": "phase", "scope_id": phase_id})
    assert resp.status_code == 200
    templates = resp.json()["data"]["templates"]
    assert len(templates) == 1
    assert templates[0]["name"] == "A"


def test_list_with_type_filter(client, db_session):
    """GET 按 type 过滤。"""
    scope_id = str(uuid4())
    _add_template(db_session, scope_id=scope_id, type="前置", name="A")
    _add_template(db_session, scope_id=scope_id, type="后置", name="B")

    resp = client.get(_API, params={"scope_type": "phase", "scope_id": scope_id, "type": "后置"})
    assert resp.status_code == 200
    templates = resp.json()["data"]["templates"]
    assert len(templates) == 1
    assert templates[0]["type"] == "后置"


def test_list_with_status_filter(client, db_session):
    """GET 按 status 过滤。"""
    scope_id = str(uuid4())
    _add_template(db_session, scope_id=scope_id, name="A", status="active")
    _add_template(db_session, scope_id=scope_id, name="B", status="inactive")

    resp = client.get(_API, params={"status": "inactive"})
    assert resp.status_code == 200
    templates = resp.json()["data"]["templates"]
    assert len(templates) == 1
    assert templates[0]["name"] == "B"


def test_list_merged_by_task(client, db_session):
    """GET ?task_id=X：合并查询（阶段优先专题，同名去重）。"""
    goal, themes, phases = make_tree(db_session, tasks_per_phase=1)
    phase_id = phases[0].id
    theme_id = themes[0].id
    task = db_session.query(Task).filter_by(phase_id=phase_id).first()

    # 阶段级 + 专题级同名 -> 阶段级优先
    _add_template(
        db_session,
        scope_type="phase",
        scope_id=phase_id,
        type="前置",
        name="准备题目",
        description="阶段级",
    )
    _add_template(
        db_session,
        scope_type="theme",
        scope_id=theme_id,
        type="前置",
        name="准备题目",
        description="专题级",
    )
    _add_template(db_session, scope_type="theme", scope_id=theme_id, type="前置", name="专题独有")

    resp = client.get(_API, params={"task_id": task.id, "type": "前置"})
    assert resp.status_code == 200
    templates = resp.json()["data"]["templates"]
    # 同名去重 -> 2 条（"准备题目" 阶段级 + "专题独有"）
    names = {t["name"] for t in templates}
    assert names == {"准备题目", "专题独有"}
    # 阶段级优先
    prep = [t for t in templates if t["name"] == "准备题目"][0]
    assert prep["description"] == "阶段级"


def test_list_merged_by_task_invalid_type_returns_400(client, db_session):
    """GET ?task_id=X&type=非法 -> 400 (1002)，type 校验在 task_id 分支也生效。"""
    goal, themes, phases = make_tree(db_session, tasks_per_phase=1)
    task = db_session.query(Task).filter_by(phase_id=phases[0].id).first()

    resp = client.get(_API, params={"task_id": task.id, "type": "中间"})
    assert resp.status_code == 400
    assert resp.json()["code"] == 1002


# ===== POST /subtask-templates =====


def test_create_success(client, db_session):
    """POST 创建模板成功。"""
    resp = client.post(
        _API,
        json={
            "scope_type": "phase",
            "scope_id": "phase-001",
            "type": "前置",
            "name": "准备题目与代码框架",
            "description": "算法基础阶段",
        },
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["id"] is not None
    assert data["scope_type"] == "phase"
    assert data["type"] == "前置"
    assert data["name"] == "准备题目与代码框架"
    assert data["status"] == "active"
    assert data["created_at"] is not None
    assert data["updated_at"] is not None


def test_create_unique_conflict_returns_3001(client, db_session):
    """POST UNIQUE 冲突 -> 3001。"""
    scope_id = str(uuid4())
    _add_template(db_session, scope_id=scope_id, type="前置", name="准备题目")

    resp = client.post(
        _API,
        json={
            "scope_type": "phase",
            "scope_id": scope_id,
            "type": "前置",
            "name": "准备题目",
        },
    )
    assert resp.status_code == 409
    body = resp.json()
    assert body["code"] == 3001
    assert "已存在" in body["message"]


def test_create_invalid_scope_type_returns_400(client, db_session):
    """POST 非法 scope_type -> 400 (1002)。"""
    resp = client.post(
        _API,
        json={"scope_type": "goal", "scope_id": "x", "type": "前置", "name": "x"},
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == 1002


def test_create_does_not_validate_theme_type(client, db_session):
    """配置时不校验专题 type（doc/01 S7 AC：配置时不校验专题类型）。"""
    resp = client.post(
        _API,
        json={
            "scope_type": "theme",
            "scope_id": "agent-theme-id",
            "type": "前置",
            "name": "智能体专题的前置",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "active"


def test_create_same_name_different_type_ok(client, db_session):
    """同 scope_id 下不同 type 同 name 不冲突。"""
    scope_id = "scope-001"
    resp1 = client.post(
        _API,
        json={"scope_type": "phase", "scope_id": scope_id, "type": "前置", "name": "笔记归档"},
    )
    assert resp1.status_code == 200

    resp2 = client.post(
        _API,
        json={"scope_type": "phase", "scope_id": scope_id, "type": "后置", "name": "笔记归档"},
    )
    assert resp2.status_code == 200


# ===== PUT /subtask-templates/{id} =====


def test_update_name_success(client, db_session):
    """PUT 更新 name 成功。"""
    t = _add_template(db_session, name="旧名")
    resp = client.put(f"{_API}/{t.id}", json={"name": "新名"})
    assert resp.status_code == 200
    assert resp.json()["data"]["name"] == "新名"


def test_update_name_conflict_returns_3001(client, db_session):
    """PUT name 冲突 -> 3001。"""
    scope_id = str(uuid4())
    _add_template(db_session, scope_id=scope_id, type="前置", name="A")
    t_b = _add_template(db_session, scope_id=scope_id, type="前置", name="B")

    resp = client.put(f"{_API}/{t_b.id}", json={"name": "A"})
    assert resp.status_code == 409
    assert resp.json()["code"] == 3001


def test_update_status_to_inactive(client, db_session):
    """PUT 更新 status。"""
    t = _add_template(db_session, name="X")
    resp = client.put(f"{_API}/{t.id}", json={"status": "inactive"})
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "inactive"


def test_update_not_found_returns_404(client, db_session):
    """PUT 不存在 -> 404。"""
    resp = client.put(f"{_API}/nonexistent", json={"name": "x"})
    assert resp.status_code == 404
    assert resp.json()["code"] == 1001


# ===== DELETE /subtask-templates/{id} =====


def test_delete_marks_inactive(client, db_session):
    """DELETE 标记 inactive（非物理删除）。"""
    t = _add_template(db_session, name="X")
    resp = client.delete(f"{_API}/{t.id}")
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "inactive"
    # 非物理删除：DB 中仍存在
    db_session.flush()
    assert db_session.get(SubtaskTemplate, t.id) is not None
    assert db_session.get(SubtaskTemplate, t.id).status == "inactive"


def test_delete_idempotent(client, db_session):
    """DELETE 已 inactive 的再删幂等（不报错）。"""
    t = _add_template(db_session, name="X", status="inactive")
    resp = client.delete(f"{_API}/{t.id}")
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "inactive"


def test_delete_recoverable(client, db_session):
    """DELETE 后可通过 PUT 恢复（status 改回 active）。"""
    t = _add_template(db_session, name="X")
    # 删除
    resp = client.delete(f"{_API}/{t.id}")
    assert resp.status_code == 200
    # 恢复
    resp = client.put(f"{_API}/{t.id}", json={"status": "active"})
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "active"


def test_delete_not_found_returns_404(client, db_session):
    """DELETE 不存在 -> 404。"""
    resp = client.delete(f"{_API}/nonexistent")
    assert resp.status_code == 404
    assert resp.json()["code"] == 1001
