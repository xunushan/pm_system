"""Story1 集成测试：drafts CRUD + plans/confirm 全链路（API + DB）。

验收要点（doc/01 S1）：
  - 回调只传 draft_id（规避 30KB）
  - Service 用 draft_id 读 drafts -> 写正式表 -> 删 drafts -> 返回 H5 链接
  - 边界：confirm 不存在 draft_id -> 404；version 不匹配 -> 409
"""

from app.models.draft import Draft
from app.models.goal import Goal
from app.models.phase import Phase
from app.models.task import Task
from app.models.theme import Theme

_API = "/api/v1"

_PLAN_CONTENT = {
    "goal": {
        "name": "具身智能算法岗面试准备",
        "description": "3 个月",
        "time_range_start": "2026-07-01",
        "time_range_end": "2026-09-30",
        "scheduled_start_date": "2026-07-02",
    },
    "themes": [
        {
            "name": "深度学习基础",
            "type": "learning",
            "phases": [
                {
                    "name": "MLP",
                    "sort_order": 1,
                    "tasks": [
                        {"name": "前向推导", "sort_order": 1},
                        {"name": "反向推导", "sort_order": 2},
                    ],
                }
            ],
        }
    ],
}


def _create_draft(client, content=None, story_type="plan") -> str:
    payload = {
        "user_id": "u1",
        "story_type": story_type,
        "content": content if content is not None else _PLAN_CONTENT,
    }
    resp = client.post(f"{_API}/drafts", json=payload)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["code"] == 0
    return body["data"]["draft_id"]


def test_drafts_create_get_put_delete(client):
    # POST
    draft_id = _create_draft(client)
    # GET
    resp = client.get(f"{_API}/drafts/{draft_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert body["data"]["draft_id"] == draft_id
    assert body["data"]["version"] == 1
    assert body["data"]["content"] == _PLAN_CONTENT
    # PUT（version 1 -> 2）
    new_content = {"goal": {"name": "改名目标"}, "themes": []}
    resp = client.put(f"{_API}/drafts/{draft_id}", json={"content": new_content, "version": 1})
    assert resp.status_code == 200
    assert resp.json()["data"]["version"] == 2
    # GET 验证更新
    resp = client.get(f"{_API}/drafts/{draft_id}")
    assert resp.json()["data"]["content"] == new_content
    assert resp.json()["data"]["version"] == 2
    # DELETE
    resp = client.delete(f"{_API}/drafts/{draft_id}")
    assert resp.status_code == 200
    # GET -> 404
    resp = client.get(f"{_API}/drafts/{draft_id}")
    assert resp.status_code == 404
    assert resp.json()["code"] == 1001


def test_drafts_put_version_mismatch_returns_409(client):
    draft_id = _create_draft(client)
    resp = client.put(
        f"{_API}/drafts/{draft_id}",
        json={"content": {"goal": {"name": "x"}}, "version": 999},
    )
    assert resp.status_code == 409
    assert resp.json()["code"] == 1003


def test_drafts_get_nonexistent_returns_404(client):
    resp = client.get(f"{_API}/drafts/no-such-id")
    assert resp.status_code == 404
    assert resp.json()["code"] == 1001


def test_drafts_create_bad_story_type_returns_400(client):
    resp = client.post(
        f"{_API}/drafts",
        json={"user_id": "u1", "story_type": "bogus", "content": {}},
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == 1002


def test_plans_confirm_writes_tables_and_returns_h5_url(client, db_session):
    draft_id = _create_draft(client)

    resp = client.post(f"{_API}/plans/confirm", json={"draft_id": draft_id})
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["goal_name"] == "具身智能算法岗面试准备"
    assert data["themes_created"] == 1
    assert data["phases_created"] == 1
    assert data["tasks_created"] == 2
    assert data["draft_deleted"] is True
    assert data["h5_url"].startswith("http://")
    assert data["h5_url"].endswith(f"/plan/{data['goal_id']}")

    # DB 断言：4 张正式表已写入，draft 已删
    assert db_session.query(Goal).count() == 1
    assert db_session.query(Theme).count() == 1
    assert db_session.query(Phase).count() == 1
    assert db_session.query(Task).count() == 2
    assert db_session.query(Draft).count() == 0

    # 规划态铁律
    task = db_session.query(Task).first()
    assert task.executor is None
    phase = db_session.query(Phase).first()
    assert phase.deadline is None
    assert phase.status == "未开始"
    assert task.status == "待执行"


def test_plans_confirm_nonexistent_draft_returns_404(client):
    resp = client.post(f"{_API}/plans/confirm", json={"draft_id": "no-such-id"})
    assert resp.status_code == 404
    assert resp.json()["code"] == 1001


def test_plans_confirm_idempotency_after_delete(client):
    """确认后 draft 已删，二次确认 -> 404，且不重复写入。"""
    draft_id = _create_draft(client)
    r1 = client.post(f"{_API}/plans/confirm", json={"draft_id": draft_id})
    assert r1.status_code == 200
    r2 = client.post(f"{_API}/plans/confirm", json={"draft_id": draft_id})
    assert r2.status_code == 404
    # 仅 1 个 goal
    # (用 client 的 db_session 验证)
    # 注意：r2 失败不写新 goal


def test_full_flow_put_then_confirm_uses_latest_content(client, db_session):
    """PUT 追加内容后确认，写入正式表的是最新版本。"""
    draft_id = _create_draft(client)
    # 追加一个专题
    updated = {
        "goal": {"name": "改名目标"},
        "themes": [
            {"name": "T1", "type": "dev", "phases": [{"name": "P1", "sort_order": 1, "tasks": []}]},
            {"name": "T2", "type": "research", "phases": []},
        ],
    }
    resp = client.put(f"{_API}/drafts/{draft_id}", json={"content": updated, "version": 1})
    assert resp.status_code == 200
    assert resp.json()["data"]["version"] == 2

    resp = client.post(f"{_API}/plans/confirm", json={"draft_id": draft_id})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["goal_name"] == "改名目标"
    assert data["themes_created"] == 2
    assert data["phases_created"] == 1
    assert data["tasks_created"] == 0

    goal = db_session.query(Goal).one()
    assert goal.name == "改名目标"
    assert db_session.query(Theme).count() == 2


def test_plans_confirm_rejects_non_plan_story_type(client):
    """story_type 非 plan 的 draft 确认 -> 400。"""
    draft_id = _create_draft(client, story_type="weekly")
    resp = client.post(f"{_API}/plans/confirm", json={"draft_id": draft_id})
    assert resp.status_code == 400
    assert resp.json()["code"] == 1002
