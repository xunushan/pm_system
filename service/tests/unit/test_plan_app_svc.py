"""PlanAppSvc.confirm 单元测试：事务写入 4 张正式表 + draft 删除 + 规划态铁律。

直连 db_session，断言：goals/themes/phases/tasks 行数、初始状态、executor=NULL、
phases.deadline=NULL、draft 已删、H5 链接。
"""

import pytest

from app.core.exceptions import BadRequestError, ConflictError, DraftExpiredError, NotFoundError
from app.models.draft import Draft
from app.models.goal import Goal
from app.models.phase import Phase
from app.models.task import Task
from app.models.theme import Theme
from app.services.draft_app_svc import DraftAppSvc
from app.services.plan_app_svc import PlanAppSvc

# 完整四层结构（1 目标 / 2 专题 / 3 阶段 / 5 任务）
_PLAN = {
    "goal": {
        "name": "具身智能算法岗面试准备",
        "description": "3 个月规划",
        "time_range_start": "2026-07-01",
        "time_range_end": "2026-09-30",
        "scheduled_start_date": "2026-07-02",
    },
    "themes": [
        {
            "name": "深度学习基础",
            "description": "DL 基础",
            "type": "learning",
            "phases": [
                {
                    "name": "神经网络基础与 MLP",
                    "sort_order": 1,
                    "tasks": [
                        {"name": "前向推导", "sort_order": 1},
                        {"name": "反向推导", "sort_order": 2},
                    ],
                },
                {
                    "name": "优化器",
                    "sort_order": 2,
                    "tasks": [{"name": "SGD", "sort_order": 1}],
                },
            ],
        },
        {
            "name": "面试准备",
            "type": "source",
            "phases": [
                {
                    "name": "算法基础",
                    "sort_order": 1,
                    "tasks": [
                        {"name": "动态规划", "sort_order": 1},
                        {"name": "手撕代码", "sort_order": 2},
                    ],
                }
            ],
        },
    ],
}


def _seed_draft(db_session) -> str:
    svc = DraftAppSvc(db_session)
    return svc.create(user_id="u1", story_type="plan", content=_PLAN).draft_id


def test_confirm_writes_all_four_tables_and_deletes_draft(db_session):
    draft_id = _seed_draft(db_session)

    result = PlanAppSvc(db_session).confirm(draft_id)

    assert result.themes_created == 2
    assert result.phases_created == 3
    assert result.tasks_created == 5
    assert result.draft_deleted is True
    assert result.goal_name == "具身智能算法岗面试准备"
    assert result.h5_url == f"http://localhost:5173/plan/{result.goal_id}"

    # 行数断言
    assert db_session.query(Goal).count() == 1
    assert db_session.query(Theme).count() == 2
    assert db_session.query(Phase).count() == 3
    assert db_session.query(Task).count() == 5
    # draft 已删
    assert db_session.query(Draft).count() == 0


def test_confirm_sets_initial_status(db_session):
    """规划态铁律：goals/themes/phases='未开始'，tasks='待执行'。"""
    draft_id = _seed_draft(db_session)
    PlanAppSvc(db_session).confirm(draft_id)

    goal = db_session.query(Goal).one()
    assert goal.status == "未开始"
    assert goal.time_range_start.isoformat() == "2026-07-01"
    assert goal.scheduled_start_date.isoformat() == "2026-07-02"

    for theme in db_session.query(Theme).all():
        assert theme.status == "未开始"
    for phase in db_session.query(Phase).all():
        assert phase.status == "未开始"
        assert phase.deadline is None  # 规划态不填
        assert phase.activated_at is None
    for task in db_session.query(Task).all():
        assert task.status == "待执行"
        assert task.executor is None  # 规划态不填
        assert task.has_subtask is False


def test_confirm_fk_chain_intact(db_session):
    """goal->theme->phase->task 外键链完整。"""
    draft_id = _seed_draft(db_session)
    PlanAppSvc(db_session).confirm(draft_id)

    task = db_session.query(Task).first()
    phase = db_session.query(Phase).filter(Phase.id == task.phase_id).one()
    theme = db_session.query(Theme).filter(Theme.id == phase.theme_id).one()
    goal = db_session.query(Goal).filter(Goal.id == theme.goal_id).one()
    assert goal.name == "具身智能算法岗面试准备"
    assert task.name in {"前向推导", "反向推导", "SGD", "动态规划", "手撕代码"}


def test_confirm_nonexistent_draft_404(db_session):
    with pytest.raises(NotFoundError):
        PlanAppSvc(db_session).confirm("no-such-draft")


def test_confirm_already_confirmed_draft_404(db_session):
    """确认后 draft 已删，二次确认 -> 404。"""
    draft_id = _seed_draft(db_session)
    PlanAppSvc(db_session).confirm(draft_id)
    with pytest.raises(NotFoundError):
        PlanAppSvc(db_session).confirm(draft_id)


def test_confirm_rejects_non_plan_story_type(db_session):
    """story_type 非 plan 的 draft 不能确认。"""
    draft_id = (
        DraftAppSvc(db_session).create(user_id="u1", story_type="weekly", content=_PLAN).draft_id
    )
    with pytest.raises(BadRequestError):
        PlanAppSvc(db_session).confirm(draft_id)


def test_confirm_rejects_malformed_content(db_session):
    """content 结构不合法 -> 1002。"""
    draft_id = (
        DraftAppSvc(db_session)
        .create(user_id="u1", story_type="plan", content={"no_goal": True})
        .draft_id
    )
    with pytest.raises(BadRequestError):
        PlanAppSvc(db_session).confirm(draft_id)


def test_confirm_empty_themes_ok(db_session):
    """仅有 goal、无专题也是合法规划（最小可用）。"""
    draft_id = (
        DraftAppSvc(db_session)
        .create(user_id="u1", story_type="plan", content={"goal": {"name": "G"}, "themes": []})
        .draft_id
    )
    result = PlanAppSvc(db_session).confirm(draft_id)
    assert result.themes_created == 0
    assert result.phases_created == 0
    assert result.tasks_created == 0
    assert db_session.query(Goal).count() == 1


def test_confirm_h5_url_uses_goal_id(db_session):
    draft_id = _seed_draft(db_session)
    result = PlanAppSvc(db_session).confirm(draft_id)
    goal = db_session.query(Goal).one()
    assert result.h5_url.endswith(f"/plan/{goal.id}")


def test_confirm_expired_draft_raises_expired(db_session):
    """P2-3: draft 过期 -> DraftExpiredError (code 1007)。"""
    from datetime import timedelta

    from app.services.draft_app_svc import now_utc_naive

    draft_id = _seed_draft(db_session)
    draft = db_session.get(Draft, draft_id)
    draft.expires_at = now_utc_naive() - timedelta(hours=1)
    db_session.commit()

    with pytest.raises(DraftExpiredError):
        PlanAppSvc(db_session).confirm(draft_id)


def test_confirm_concurrent_draft_delete_raises_conflict(db_session):
    """P1-2: draft 删除失败（并发已删）-> ConflictError + 事务回滚不写正式表。"""
    draft_id = _seed_draft(db_session)
    svc = PlanAppSvc(db_session)
    # 模拟并发：draft_repo.delete 返回 False（行已不存在）
    svc.draft_repo.delete = lambda _id: False  # noqa: E731

    with pytest.raises(ConflictError):
        svc.confirm(draft_id)
    # 事务未提交 -> 回滚后正式表无写入
    db_session.rollback()
    assert db_session.query(Goal).count() == 0
    assert db_session.query(Theme).count() == 0
