"""Story8 单元测试：阶段衔接建议逻辑（linking.py）。

纯计算 + DB 查询，无 IO/HTTP。测试：
  - find_next_phase: sort_order+1 正确查找
  - compute_suggested_deadline: 合理推算
  - get_linking_status: 当前衔接状态查询
"""

from datetime import date

from app.supervisor import linking
from tests._factory import make_tree


def test_find_next_phase_correct(db_session):
    """查同专题 sort_order+1 下一阶段。"""
    goal, themes, phases = make_tree(db_session, n_themes=1, phases_per_theme=3)
    db_session.flush()

    next_p = linking.find_next_phase(db_session, phases[0].id)
    assert next_p is not None
    assert next_p.id == phases[1].id
    assert next_p.sort_order == phases[1].sort_order


def test_find_next_phase_none_when_last(db_session):
    """最后一个阶段 -> None（专题将完成）。"""
    goal, themes, phases = make_tree(db_session, n_themes=1, phases_per_theme=3)
    db_session.flush()

    assert linking.find_next_phase(db_session, phases[2].id) is None


def test_find_next_phase_phase_not_exists(db_session):
    """phase_id 不存在 -> None。"""
    assert linking.find_next_phase(db_session, "nonexistent") is None


def test_compute_suggested_deadline_with_time_range(db_session):
    """有 time_range_end -> 剩余时间/剩余阶段数。"""
    goal, themes, phases = make_tree(db_session, n_themes=1, phases_per_theme=2)
    goal.time_range_end = date(2026, 7, 20)
    goal.status = "进行中"
    db_session.flush()

    # next_phase = phases[1] (sort_order=2)
    deadline = linking.compute_suggested_deadline(db_session, phases[1])
    assert deadline is not None
    # 应该是 today + (remaining_days / remaining_phases)
    # remaining_phases = 1 (only phases[1] is 未开始)
    # remaining_days = time_range_end - today


def test_compute_suggested_deadline_no_time_range(db_session):
    """无 time_range_end -> 默认 7 天/阶段。"""
    goal, themes, phases = make_tree(db_session, n_themes=1, phases_per_theme=2)
    db_session.flush()

    deadline = linking.compute_suggested_deadline(db_session, phases[1])
    assert deadline is not None
    # 大致 7 天后


def test_get_linking_status_with_active_phase(db_session):
    """有进行中阶段 -> 返回下一阶段 + 建议 deadline。"""
    goal, themes, phases = make_tree(db_session, n_themes=1, phases_per_theme=2)
    goal.status = "进行中"
    themes[0].status = "进行中"
    phases[0].status = "进行中"
    phases[0].activated_at = date(2026, 7, 1)
    db_session.flush()

    next_phase_id, suggested_deadline = linking.get_linking_status(db_session)
    assert next_phase_id == phases[1].id
    assert suggested_deadline is not None


def test_get_linking_status_no_active_phase(db_session):
    """无进行中/已完成阶段 -> (None, None)。"""
    goal, themes, phases = make_tree(db_session, n_themes=1, phases_per_theme=2)
    db_session.flush()

    next_phase_id, suggested_deadline = linking.get_linking_status(db_session)
    assert next_phase_id is None
    assert suggested_deadline is None


def test_get_linking_status_no_next_phase(db_session):
    """进行中阶段是最后一个 -> 无下一阶段 (None, None)。"""
    goal, themes, phases = make_tree(db_session, n_themes=1, phases_per_theme=1)
    goal.status = "进行中"
    themes[0].status = "进行中"
    phases[0].status = "进行中"
    phases[0].activated_at = date(2026, 7, 1)
    db_session.flush()

    next_phase_id, suggested_deadline = linking.get_linking_status(db_session)
    assert next_phase_id is None
    assert suggested_deadline is None


def test_get_linking_status_recently_completed(db_session):
    """无进行中但有最近完成 -> 查其下一阶段。"""
    goal, themes, phases = make_tree(db_session, n_themes=1, phases_per_theme=2)
    goal.status = "进行中"
    themes[0].status = "进行中"
    phases[0].status = "已完成"
    phases[0].activated_at = date(2026, 7, 1)
    from app.core.times import now_utc_naive

    phases[0].completed_at = now_utc_naive()
    db_session.flush()

    next_phase_id, suggested_deadline = linking.get_linking_status(db_session)
    assert next_phase_id == phases[1].id
