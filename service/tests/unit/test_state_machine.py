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
