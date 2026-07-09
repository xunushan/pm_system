"""时间工具：UTC naive datetime（与 SQLite 存储一致）。

提取自 draft_app_svc 以解循环（core 件不应依赖 service 层）。
SQLite 存 naive datetime；datetime.now(UTC) 是 tz-aware，需 strip tzinfo 后比较。
"""

from datetime import UTC, datetime


def now_utc_naive() -> datetime:
    """当前 UTC 时间（naive，与 SQLite 存储一致）。"""
    return datetime.now(UTC).replace(tzinfo=None)
