"""state_machine 单元测试：forward 合法/非法流转。详见 doc/02 2.16。"""

import pytest

from app.core.state_machine import validate_transition


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


def test_pause_raises_not_implemented():
    """pause/resume/revert 由 S5 实现，当前抛 NotImplementedError。"""
    with pytest.raises(NotImplementedError):
        validate_transition("phase", "进行中", "已暂停", reason="x")
    with pytest.raises(NotImplementedError):
        validate_transition("phase", "已完成", "进行中", reason="x")


def test_illegal_transition_raises_value_error():
    """完全非法的流转抛 ValueError。"""
    with pytest.raises(ValueError):
        validate_transition("phase", "已完成", "未开始", reason=None)
    with pytest.raises(ValueError):
        validate_transition("task", "已完成", "未开始", reason=None)
    with pytest.raises(ValueError):
        validate_transition("goal", "未开始", "已完成", reason=None)
