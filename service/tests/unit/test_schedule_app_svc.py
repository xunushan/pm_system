"""ScheduleAppSvc 单元测试：名额/锁定/managed/deadline 校验 + 激活核心事务。

直接调 AppSvc（不经 HTTP），用 db_session 断言 DB 状态。HTTP 链路见 integration。
"""

from datetime import date

import pytest

from app.core.exceptions import BadRequestError, ConflictError, NotFoundError, QuotaExceededError
from app.models.phase import Phase
from app.models.status_change_log import StatusChangeLog
from app.models.workspace import Workspace
from app.schemas.schedule import ScheduleItem
from app.services.schedule_app_svc import ScheduleAppSvc
from tests._factory import make_tree


def _confirm(db, goal_id, items):
    return ScheduleAppSvc(db).confirm(user_id="u1", goal_id=goal_id, items=items)


def test_confirm_activates_first_phase_and_cascades(db_session):
    """成功：激活 sort_order=1 phase，级联 theme/goal，建 workspace，写 forward+cascade 审计。"""
    goal, themes, phases = make_tree(db_session, n_themes=1, phases_per_theme=2)
    db_session.flush()

    data = _confirm(
        db_session,
        goal.id,
        [ScheduleItem(theme_id=themes[0].id, managed=True, deadline=date(2026, 7, 15))],
    )

    # 激活 sort_order=1
    activated = data.activated_phases[0]
    assert activated.phase_id == phases[0].id
    assert phases[0].status == "进行中"
    assert phases[0].activated_at is not None
    assert phases[0].deadline == date(2026, 7, 15)
    # 另一个 phase 未动
    assert phases[1].status == "未开始"
    # 级联
    assert themes[0].status == "进行中"
    assert goal.status == "进行中"
    # workspace 记录
    assert db_session.query(Workspace).count() == 1
    ws = db_session.query(Workspace).one()
    assert ws.managed is True
    assert ws.status == "未初始化"
    assert ws.type == "learning"
    # 审计：1 forward(phase) + 2 cascade(theme, goal)
    types = [log.change_type for log in db_session.query(StatusChangeLog).all()]
    assert types.count("forward") == 1
    assert types.count("cascade") == 2
    assert data.scheduled_start_date == goal.scheduled_start_date


def test_confirm_quota_exceeded_returns_409(db_session):
    """3 个进行中 + 本次 1 -> 超 3 上限 -> 409(1004 并发超限)。"""
    goal, themes, phases = make_tree(db_session, n_themes=4, phases_per_theme=1)
    for p in phases[:3]:
        p.status = "进行中"
    db_session.flush()

    with pytest.raises(QuotaExceededError):
        _confirm(
            db_session,
            goal.id,
            [ScheduleItem(theme_id=themes[3].id, managed=True, deadline=date(2026, 7, 15))],
        )


def test_confirm_theme_already_active_returns_409(db_session):
    """theme 已有进行中 phase -> 409（阶段强约束，应走衔接）。"""
    goal, themes, phases = make_tree(db_session, n_themes=1, phases_per_theme=2)
    phases[0].status = "进行中"
    db_session.flush()

    with pytest.raises(ConflictError):
        _confirm(
            db_session,
            goal.id,
            [ScheduleItem(theme_id=themes[0].id, managed=True, deadline=date(2026, 7, 15))],
        )


def test_confirm_no_inactive_phase_returns_409(db_session):
    """theme 无未开始阶段（全已完成）-> 409。"""
    goal, themes, phases = make_tree(db_session, n_themes=1, phases_per_theme=1)
    phases[0].status = "已完成"
    db_session.flush()

    with pytest.raises(ConflictError):
        _confirm(
            db_session,
            goal.id,
            [ScheduleItem(theme_id=themes[0].id, managed=True, deadline=date(2026, 7, 15))],
        )


def test_confirm_phase_id_mismatch_returns_400(db_session):
    """item.phase_id 与锁定的阶段不一致 -> 400。"""
    goal, themes, phases = make_tree(db_session, n_themes=1, phases_per_theme=2)
    db_session.flush()

    with pytest.raises(BadRequestError):
        _confirm(
            db_session,
            goal.id,
            [
                ScheduleItem(
                    theme_id=themes[0].id,
                    managed=True,
                    deadline=date(2026, 7, 15),
                    phase_id="wrong-id",
                )
            ],
        )


def test_confirm_deadline_missing_returns_400(db_session):
    """deadline 缺失 -> 400(1002)。"""
    goal, themes, _phases = make_tree(db_session)
    db_session.flush()

    with pytest.raises(BadRequestError):
        _confirm(
            db_session,
            goal.id,
            [ScheduleItem(theme_id=themes[0].id, managed=True, deadline=None)],
        )


def test_confirm_managed0_path_missing_returns_400(db_session):
    """managed=0 且 path 缺失 -> 400。"""
    goal, themes, _phases = make_tree(db_session)
    db_session.flush()

    with pytest.raises(BadRequestError):
        _confirm(
            db_session,
            goal.id,
            [
                ScheduleItem(
                    theme_id=themes[0].id, managed=False, path=None, deadline=date(2026, 7, 15)
                )
            ],
        )


def test_confirm_managed0_path_not_exists_returns_400(db_session):
    """managed=0 且 path 不存在 -> 400(1002)。"""
    goal, themes, _phases = make_tree(db_session)
    db_session.flush()

    with pytest.raises(BadRequestError):
        _confirm(
            db_session,
            goal.id,
            [
                ScheduleItem(
                    theme_id=themes[0].id,
                    managed=False,
                    path="/nonexistent-xyz-12345",
                    deadline=date(2026, 7, 15),
                )
            ],
        )


def test_confirm_managed0_valid_path_sets_ready(db_session, tmp_path):
    """managed=0 且 path 存在 -> workspace 直接已就绪（不创建文件）。"""
    goal, themes, _phases = make_tree(db_session)
    db_session.flush()
    existing_dir = tmp_path / "existing"
    existing_dir.mkdir()

    data = _confirm(
        db_session,
        goal.id,
        [
            ScheduleItem(
                theme_id=themes[0].id,
                managed=False,
                path=str(existing_dir),
                deadline=date(2026, 7, 20),
            )
        ],
    )

    ws = db_session.query(Workspace).one()
    assert ws.managed is False
    assert ws.status == "已就绪"
    assert ws.path == str(existing_dir)
    assert data.activated_phases[0].workspace_status == "已就绪"
    # 不创建任何文件（目录原有内容不变）
    assert existing_dir.exists()


def test_confirm_goal_not_found_returns_404(db_session):
    with pytest.raises(NotFoundError):
        _confirm(
            db_session,
            "no-such-goal",
            [ScheduleItem(theme_id="t", managed=True, deadline=date(2026, 7, 15))],
        )


def test_confirm_multi_themes_uses_3_quota(db_session):
    """一次激活 2 个专题（各 1 phase），占用名额 2，theme/goal 各级联。"""
    goal, themes, _phases = make_tree(db_session, n_themes=2, phases_per_theme=1)
    db_session.flush()

    data = _confirm(
        db_session,
        goal.id,
        [
            ScheduleItem(theme_id=themes[0].id, managed=True, deadline=date(2026, 7, 15)),
            ScheduleItem(theme_id=themes[1].id, managed=True, deadline=date(2026, 7, 16)),
        ],
    )

    assert len(data.activated_phases) == 2
    assert db_session.query(Phase).filter_by(status="进行中").count() == 2
    assert db_session.query(Workspace).count() == 2
