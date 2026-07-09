"""state_machine 单元测试：forward + pause/resume/revert reason 校验。详见 doc/02 2.16。"""

import pytest

from app.core.exceptions import ReasonRequiredError
from app.core.state_machine import validate_transition

# ===== forward 流转（合法，reason 不要求）=====


@pytest.mark.parametrize(
    ("entity", "frm", "to"),
    [
        ("goal", "未开始", "进行中"),
        ("theme", "未开始", "进行中"),
        ("phase", "未开始", "进行中"),
        ("phase", "进行中", "已完成"),
        ("task", "待执行", "已完成"),
    ],
)
def test_forward_transitions_valid(entity, frm, to):
    """forward 正向流转合法，reason 不要求。"""
    validate_transition(entity, frm, to, reason=None)


# ===== pause：reason 必填 =====


@pytest.mark.parametrize(
    ("entity", "frm", "to"),
    [
        ("phase", "进行中", "已暂停"),
        ("task", "待执行", "已暂停"),
    ],
)
def test_pause_requires_reason(entity, frm, to):
    """pause 缺 reason -> ReasonRequiredError(code=1005)。"""
    with pytest.raises(ReasonRequiredError) as exc_info:
        validate_transition(entity, frm, to, reason=None)
    assert exc_info.value.code == 1005


@pytest.mark.parametrize(
    ("entity", "frm", "to"),
    [
        ("phase", "进行中", "已暂停"),
        ("task", "待执行", "已暂停"),
    ],
)
def test_pause_with_reason_valid(entity, frm, to):
    """pause 有 reason -> 合法。"""
    validate_transition(entity, frm, to, reason="暂停原因")


# ===== revert：reason 必填 =====


@pytest.mark.parametrize(
    ("entity", "frm", "to"),
    [
        ("phase", "已完成", "进行中"),
        ("task", "已完成", "待执行"),
    ],
)
def test_revert_requires_reason(entity, frm, to):
    """revert 缺 reason -> ReasonRequiredError(code=1005)。"""
    with pytest.raises(ReasonRequiredError) as exc_info:
        validate_transition(entity, frm, to, reason=None)
    assert exc_info.value.code == 1005


@pytest.mark.parametrize(
    ("entity", "frm", "to"),
    [
        ("phase", "已完成", "进行中"),
        ("task", "已完成", "待执行"),
    ],
)
def test_revert_with_reason_valid(entity, frm, to):
    """revert 有 reason -> 合法。"""
    validate_transition(entity, frm, to, reason="回退原因")


# ===== resume：reason 不要求 =====


@pytest.mark.parametrize(
    ("entity", "frm", "to"),
    [
        ("phase", "已暂停", "进行中"),
        ("task", "已暂停", "待执行"),
    ],
)
def test_resume_no_reason_required(entity, frm, to):
    """resume 不要求 reason。"""
    validate_transition(entity, frm, to, reason=None)


# ===== goal/theme pause/resume/revert（S9 board 扩展）=====


@pytest.mark.parametrize(
    ("entity", "frm", "to"),
    [
        ("goal", "进行中", "已暂停"),
        ("theme", "进行中", "已暂停"),
    ],
)
def test_goal_theme_pause_requires_reason(entity, frm, to):
    """goal/theme pause 缺 reason -> ReasonRequiredError(code=1005)。"""
    with pytest.raises(ReasonRequiredError) as exc_info:
        validate_transition(entity, frm, to, reason=None)
    assert exc_info.value.code == 1005


@pytest.mark.parametrize(
    ("entity", "frm", "to"),
    [
        ("goal", "进行中", "已暂停"),
        ("theme", "进行中", "已暂停"),
    ],
)
def test_goal_theme_pause_with_reason_valid(entity, frm, to):
    """goal/theme pause 有 reason -> 合法。"""
    validate_transition(entity, frm, to, reason="暂停原因")


@pytest.mark.parametrize(
    ("entity", "frm", "to"),
    [
        ("goal", "已完成", "进行中"),
        ("theme", "已完成", "进行中"),
    ],
)
def test_goal_theme_revert_requires_reason(entity, frm, to):
    """goal/theme revert 缺 reason -> ReasonRequiredError(code=1005)。"""
    with pytest.raises(ReasonRequiredError) as exc_info:
        validate_transition(entity, frm, to, reason=None)
    assert exc_info.value.code == 1005


@pytest.mark.parametrize(
    ("entity", "frm", "to"),
    [
        ("goal", "已完成", "进行中"),
        ("theme", "已完成", "进行中"),
    ],
)
def test_goal_theme_revert_with_reason_valid(entity, frm, to):
    """goal/theme revert 有 reason -> 合法。"""
    validate_transition(entity, frm, to, reason="回退原因")


@pytest.mark.parametrize(
    ("entity", "frm", "to"),
    [
        ("goal", "已暂停", "进行中"),
        ("theme", "已暂停", "进行中"),
    ],
)
def test_goal_theme_resume_no_reason_required(entity, frm, to):
    """goal/theme resume 不要求 reason。"""
    validate_transition(entity, frm, to, reason=None)


# ===== get_change_type（S9 board 用）=====


def test_get_change_type_forward():
    """forward 流转返回 'forward'。"""
    from app.core.state_machine import get_change_type

    assert get_change_type("phase", "未开始", "进行中") == "forward"
    assert get_change_type("task", "待执行", "已完成") == "forward"


def test_get_change_type_pause_resume_revert():
    """pause/resume/revert 流转返回对应 change_type。"""
    from app.core.state_machine import get_change_type

    assert get_change_type("phase", "进行中", "已暂停") == "pause"
    assert get_change_type("phase", "已暂停", "进行中") == "resume"
    assert get_change_type("phase", "已完成", "进行中") == "revert"
    assert get_change_type("goal", "已完成", "进行中") == "revert"
    assert get_change_type("theme", "进行中", "已暂停") == "pause"


def test_get_change_type_illegal_returns_none():
    """非法流转返回 None。"""
    from app.core.state_machine import get_change_type

    assert get_change_type("phase", "已完成", "未开始") is None
    assert get_change_type("task", "待执行", "进行中") is None


# ===== 非法流转抛 ValueError =====


@pytest.mark.parametrize(
    ("entity", "frm", "to"),
    [
        ("phase", "已完成", "未开始"),
        ("task", "已完成", "未开始"),
        ("goal", "未开始", "已完成"),
        ("phase", "未开始", "已暂停"),
        ("task", "待执行", "进行中"),  # task 无'进行中'态
        ("phase", "已暂停", "已完成"),
    ],
)
def test_illegal_transition_raises_value_error(entity, frm, to):
    """完全非法的流转抛 ValueError。"""
    with pytest.raises(ValueError):
        validate_transition(entity, frm, to, reason="x")
