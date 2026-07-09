"""Story2 集成测试：schedules/confirm 全链路（API + DB）+ 边界。

验收要点（doc/01 S2）：
  - 多选专题，每个激活其第1个未开始阶段
  - 即时级联 themes/goals 到进行中
  - 记录 phases.activated_at
  - status_change_log 有 forward + cascade 记录
  - managed=1 异步初始化；managed=0 校验 path 不创建文件
  - 全局进行中 ≤3；deadline 必填
"""

from sqlalchemy.orm import sessionmaker

from app.models.phase import Phase
from app.models.status_change_log import StatusChangeLog
from app.models.workspace import Workspace
from app.services import workspace_app_svc
from tests._factory import make_tree

_API = "/api/v1"


def _confirm_body(goal_id, items):
    return {"user_id": "u1", "goal_id": goal_id, "items": items}


def test_confirm_full_flow_managed1_and_managed0(client, db_session, tmp_path):
    """2 专题：managed=1 + managed=0(已有目录) -> 2 phase 激活 + 级联 + workspace + 审计。"""
    goal, themes, _phases = make_tree(db_session, n_themes=2, phases_per_theme=1)
    db_session.flush()
    existing_dir = tmp_path / "interview"
    existing_dir.mkdir()

    body = _confirm_body(
        goal.id,
        [
            {"theme_id": themes[0].id, "managed": True, "deadline": "2026-07-15"},
            {
                "theme_id": themes[1].id,
                "managed": False,
                "path": str(existing_dir),
                "deadline": "2026-07-20",
            },
        ],
    )
    resp = client.post(f"{_API}/schedules/confirm", json=body)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert len(data["activated_phases"]) == 2

    # DB：2 phase 进行中 + activated_at 填
    active = db_session.query(Phase).filter_by(status="进行中").all()
    assert len(active) == 2
    assert all(p.activated_at is not None for p in active)
    # 级联
    assert all(t.status == "进行中" for t in themes)
    assert goal.status == "进行中"
    # workspace
    wss = db_session.query(Workspace).all()
    assert len(wss) == 2
    managed_ws = next(w for w in wss if w.managed)
    linked_ws = next(w for w in wss if not w.managed)
    assert managed_ws.status == "未初始化"
    assert linked_ws.status == "已就绪"
    assert linked_ws.path == str(existing_dir)
    # 审计：2 forward(2 phase) + 3 cascade(2 theme 首次激活 + goal 首次级联；goal 第二次幂等)
    forward = db_session.query(StatusChangeLog).filter_by(change_type="forward").count()
    cascade_n = db_session.query(StatusChangeLog).filter_by(change_type="cascade").count()
    assert forward == 2  # 2 phase
    assert cascade_n == 3  # 2 theme + 1 goal（goal 第二次已进行中，幂等不重复写）


def test_confirm_managed1_init_async(client, db_session, monkeypatch, tmp_path):
    """managed=1 -> BackgroundTasks 调 init -> 目录创建 + workspace 置已就绪。"""
    goal, themes, _phases = make_tree(db_session, n_themes=1, phases_per_theme=1)
    db_session.flush()

    # init 用独立 SessionLocal，monkeypatch 指向测试 engine
    monkeypatch.setattr(
        workspace_app_svc,
        "SessionLocal",
        sessionmaker(bind=db_session.bind, expire_on_commit=False),
    )
    # init_workspace_dir 用 tmp_path 避免污染 cwd
    created_paths = []

    def fake_init(path):
        import os

        os.makedirs(path, exist_ok=True)
        created_paths.append(path)

    monkeypatch.setattr(workspace_app_svc, "init_workspace_dir", fake_init)

    body = _confirm_body(
        goal.id,
        [{"theme_id": themes[0].id, "managed": True, "deadline": "2026-07-15"}],
    )
    resp = client.post(f"{_API}/schedules/confirm", json=body)
    assert resp.status_code == 200, resp.text

    # BackgroundTasks 已执行（TestClient with 上下文）
    assert len(created_paths) == 1
    ws = db_session.query(Workspace).one()
    assert ws.status == "已就绪"


def test_confirm_quota_exceeded_returns_409(client, db_session):
    """3 进行中 + 1 -> 409(1004 并发超限)。"""
    goal, themes, phases = make_tree(db_session, n_themes=4, phases_per_theme=1)
    for p in phases[:3]:
        p.status = "进行中"
    db_session.flush()

    body = _confirm_body(
        goal.id,
        [{"theme_id": themes[3].id, "managed": True, "deadline": "2026-07-15"}],
    )
    resp = client.post(f"{_API}/schedules/confirm", json=body)
    assert resp.status_code == 409
    assert resp.json()["code"] == 1004


def test_confirm_reactivate_active_theme_returns_409(client, db_session):
    """theme 已有进行中 phase -> 409。"""
    goal, themes, phases = make_tree(db_session, n_themes=1, phases_per_theme=2)
    phases[0].status = "进行中"
    db_session.flush()

    body = _confirm_body(
        goal.id,
        [{"theme_id": themes[0].id, "managed": True, "deadline": "2026-07-15"}],
    )
    resp = client.post(f"{_API}/schedules/confirm", json=body)
    assert resp.status_code == 409
    assert resp.json()["code"] == 1003


def test_confirm_managed0_path_not_exists_returns_1002(client, db_session):
    """managed=0 path 不存在 -> 400(1002)。"""
    goal, themes, _phases = make_tree(db_session)
    db_session.flush()

    body = _confirm_body(
        goal.id,
        [
            {
                "theme_id": themes[0].id,
                "managed": False,
                "path": "/nonexistent-abc-999",
                "deadline": "2026-07-15",
            }
        ],
    )
    resp = client.post(f"{_API}/schedules/confirm", json=body)
    assert resp.status_code == 400
    assert resp.json()["code"] == 1002


def test_confirm_deadline_missing_returns_400(client, db_session):
    """deadline 缺失 -> 400(1002)。"""
    goal, themes, _phases = make_tree(db_session)
    db_session.flush()

    body = _confirm_body(
        goal.id,
        [{"theme_id": themes[0].id, "managed": True}],
    )
    resp = client.post(f"{_API}/schedules/confirm", json=body)
    assert resp.status_code == 400
    assert resp.json()["code"] == 1002


def test_confirm_managed0_does_not_create_files(client, db_session, tmp_path):
    """managed=0 -> 不在 path 创建任何文件。"""
    goal, themes, _phases = make_tree(db_session)
    db_session.flush()
    existing = tmp_path / "existing-dir"
    existing.mkdir()

    body = _confirm_body(
        goal.id,
        [
            {
                "theme_id": themes[0].id,
                "managed": False,
                "path": str(existing),
                "deadline": "2026-07-15",
            }
        ],
    )
    resp = client.post(f"{_API}/schedules/confirm", json=body)
    assert resp.status_code == 200
    # 目录内容不变（无 README/.gitkeep）
    assert not (existing / "README.md").exists()
    assert not (existing / ".gitkeep").exists()


def test_confirm_managed0_path_not_exists_aborts_before_db_write(client, db_session):
    """path 不存在 -> 1002，且校验在事务外（无 phase 更新/无 workspace 创建）。

    验证铁律 §3#3：path 存在性校验（isdir=IO）前置到事务外，失败时 DB 零写入。
    """
    goal, themes, phases = make_tree(db_session, phases_per_theme=1)
    db_session.flush()
    phase_before = phases[0].status

    body = _confirm_body(
        goal.id,
        [
            {
                "theme_id": themes[0].id,
                "managed": False,
                "path": "/nonexistent-preflight-999",
                "deadline": "2026-07-15",
            }
        ],
    )
    resp = client.post(f"{_API}/schedules/confirm", json=body)
    assert resp.status_code == 400
    assert resp.json()["code"] == 1002
    # DB 零写入：phase 状态未变、无 workspace
    db_session.expire_all()
    assert phases[0].status == phase_before
    assert db_session.query(Workspace).count() == 0
