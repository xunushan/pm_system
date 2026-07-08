"""状态机校验。详见《数据模型文档 v2.0》2.16。

阶段：未开始 / 进行中 / 已完成 / 已暂停
  未开始->进行中(forward) / 进行中->已完成(forward)
  进行中<->已暂停(pause/resume) / 已完成->进行中(revert, reason 必填)

任务：待执行 / 已完成 / 已暂停
  待执行->已完成(forward) / 待执行<->已暂停 / 已完成->待执行(revert, reason 必填)

暂停/回退必填 reason；恢复不填 reason。所有流转写 status_change_log。
"""

_VALID_TRANSITIONS = {
    # (entity, from, to) -> requires_reason
    # TODO(Story5/9)：填全流转表
}


def validate_transition(
    entity_type: str, from_status: str, to_status: str, reason: str | None
) -> None:
    """TODO(Story5/9)：校验状态流转合法性 + reason 必填性。非法抛 ValueError。"""
    raise NotImplementedError("Story5/9 实现 - 见 doc/02 2.16")
