"""状态变更审计：写 status_change_log。

change_type: forward / pause / resume / revert / cascade
triggered_by: user / agent_callback / supervisor / cascade
回退/暂停必填 reason。详见《数据模型文档 v2.0》2.11。
"""


def log_status_change(
    db,  # noqa: ANN001
    entity_type: str,
    entity_id: str,
    from_status: str | None,
    to_status: str,
    change_type: str,
    triggered_by: str,
    reason: str | None = None,
) -> None:
    """TODO(Story5 起)：写一条 status_change_log。"""
    raise NotImplementedError("Story5+ 实现 - 见 doc/02 2.11")
