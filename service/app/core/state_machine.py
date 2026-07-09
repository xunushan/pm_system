"""状态机校验。详见《数据模型文档 v2.0》2.16。

阶段：未开始 / 进行中 / 已完成 / 已暂停
  未开始->进行中(forward) / 进行中->已完成(forward)
  进行中<->已暂停(pause/resume) / 已完成->进行中(revert, reason 必填)

任务：待执行 / 已完成 / 已暂停
  待执行->已完成(forward) / 待执行<->已暂停 / 已完成->待执行(revert, reason 必填)

暂停/回退必填 reason；恢复不填 reason。所有流转写 status_change_log。

Story2 实现范围：仅 forward 正向流转（未开始->进行中 / 待执行->已完成）。
  forward 不要求 reason。pause/resume/revert 留 S5/9 扩展（见 NotImplementedError）。
"""

from collections.abc import Mapping

# 合法 forward 流转：(entity_type, from_status, to_status)
# forward 不要求 reason（仅 pause/revert 必填，S5 实现）
_FORWARD_TRANSITIONS: frozenset[tuple[str, str, str]] = frozenset(
    {
        ("goal", "未开始", "进行中"),
        ("theme", "未开始", "进行中"),
        ("phase", "未开始", "进行中"),
        ("phase", "进行中", "已完成"),
        ("task", "待执行", "已完成"),
    }
)

# pause/resume/revert 流转（S5/9 实现 reason 必填校验）
_PAUSED_TRANSITIONS: Mapping[tuple[str, str, str], str] = {
    # (entity, from, to): change_type -- TODO(Story5/9) 实现 reason 必填
    ("phase", "进行中", "已暂停"): "pause",
    ("phase", "已暂停", "进行中"): "resume",
    ("phase", "已完成", "进行中"): "revert",
    ("task", "待执行", "已暂停"): "pause",
    ("task", "已暂停", "待执行"): "resume",
    ("task", "已完成", "待执行"): "revert",
}


def validate_transition(
    entity_type: str, from_status: str, to_status: str, reason: str | None
) -> None:
    """校验状态流转合法性 + reason 必填性。非法抛 ValueError。

    Story2 范围：forward 流转（未开始->进行中 / 待执行->已完成）合法，reason 不要求。
    pause/resume/revert 由 S5/9 扩展（当前抛 NotImplementedError）。
    其余流转为非法（抛 ValueError）。
    """
    key = (entity_type, from_status, to_status)
    if key in _FORWARD_TRANSITIONS:
        return  # forward 合法，reason 不要求
    if key in _PAUSED_TRANSITIONS:
        change_type = _PAUSED_TRANSITIONS[key]
        raise NotImplementedError(
            f"{change_type} 流转 ({entity_type}: {from_status}->{to_status}) "
            "由 Story5/9 实现 reason 必填校验"
        )
    raise ValueError(f"非法状态流转: {entity_type} {from_status!r} -> {to_status!r}")
