"""状态机校验。详见《数据模型文档 v2.0》2.16。

阶段：未开始 / 进行中 / 已完成 / 已暂停
  未开始->进行中(forward) / 进行中->已完成(forward)
  进行中<->已暂停(pause/resume) / 已完成->进行中(revert, reason 必填)

任务：待执行 / 已完成 / 已暂停
  待执行->已完成(forward) / 待执行<->已暂停 / 已完成->待执行(revert, reason 必填)

目标/专题：未开始 / 进行中 / 已完成 / 已暂停（S9 board 扩展）
  进行中<->已暂停(pause/resume) / 已完成->进行中(revert, reason 必填)
  forward 由级联自动更新（不在 board 手动触发）

暂停/回退必填 reason；恢复不填 reason。所有流转写 status_change_log。

Story2 实现 forward 正向流转（reason 不要求）。
Story5 扩展 phase/task pause/resume/revert。
Story9 扩展 goal/theme pause/resume/revert（board H5 状态变更）。
"""

from app.core.exceptions import ReasonRequiredError

# 合法 forward 流转：(entity_type, from_status, to_status)
# forward 不要求 reason
_FORWARD_TRANSITIONS: frozenset[tuple[str, str, str]] = frozenset(
    {
        ("goal", "未开始", "进行中"),
        ("theme", "未开始", "进行中"),
        ("phase", "未开始", "进行中"),
        ("phase", "进行中", "已完成"),
        ("task", "待执行", "已完成"),
    }
)

# pause/resume/revert 流转：(entity, from, to) -> change_type
# pause/revert 必填 reason；resume 不要求
# S5 实现 phase/task；S9 board 扩展 goal/theme（doc/02 §2.16 回退规则通用：
#   "阶段/任务/专题/目标支持已暂停"，pause/resume/revert 规则一致）
_PAUSED_TRANSITIONS: dict[tuple[str, str, str], str] = {
    ("phase", "进行中", "已暂停"): "pause",
    ("phase", "已暂停", "进行中"): "resume",
    ("phase", "已完成", "进行中"): "revert",
    ("task", "待执行", "已暂停"): "pause",
    ("task", "已暂停", "待执行"): "resume",
    ("task", "已完成", "待执行"): "revert",
    # S9 board: goal/theme 支持 pause/resume/revert（与 phase 同规则）
    ("goal", "进行中", "已暂停"): "pause",
    ("goal", "已暂停", "进行中"): "resume",
    ("goal", "已完成", "进行中"): "revert",
    ("theme", "进行中", "已暂停"): "pause",
    ("theme", "已暂停", "进行中"): "resume",
    ("theme", "已完成", "进行中"): "revert",
}

# reason 必填的 change_type
_REASON_REQUIRED: frozenset[str] = frozenset({"pause", "revert"})


def validate_transition(
    entity_type: str, from_status: str, to_status: str, reason: str | None
) -> None:
    """校验状态流转合法性 + reason 必填性。

    - forward：合法，reason 不要求。
    - pause（进行中/待执行->已暂停）：reason 必填，缺失抛 ReasonRequiredError(1005)。
    - resume（已暂停->进行中/待执行）：合法，reason 不要求。
    - revert（已完成->进行中/待执行）：reason 必填，缺失抛 ReasonRequiredError(1005)。
    - 非法流转：抛 ValueError。

    Args:
        entity_type: goal/theme/phase/task
        from_status: 当前状态
        to_status: 目标状态
        reason: 变更原因（pause/revert 必填，resume/forward 不要求）

    Raises:
        ReasonRequiredError: pause/revert 缺 reason（code=1005）
        ValueError: 完全非法的流转
    """
    key = (entity_type, from_status, to_status)
    if key in _FORWARD_TRANSITIONS:
        return  # forward 合法，reason 不要求
    if key in _PAUSED_TRANSITIONS:
        change_type = _PAUSED_TRANSITIONS[key]
        if change_type in _REASON_REQUIRED and not reason:
            raise ReasonRequiredError(
                f"{change_type} 流转 ({entity_type}: {from_status}->{to_status}) 需 reason"
            )
        return  # resume 或 pause/revert（reason 已填）合法
    raise ValueError(f"非法状态流转: {entity_type} {from_status!r} -> {to_status!r}")


def get_change_type(entity_type: str, from_status: str, to_status: str) -> str | None:
    """返回状态变更类型（forward/pause/resume/revert），非法返回 None。

    S9 board 用：区分 forward（board 不提供，走 activate）与 pause/resume/revert。
    """
    key = (entity_type, from_status, to_status)
    if key in _FORWARD_TRANSITIONS:
        return "forward"
    return _PAUSED_TRANSITIONS.get(key)
