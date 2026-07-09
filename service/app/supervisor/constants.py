"""Supervisor 共享常量。

供 handlers / scheduler 共用，避免私有名（下划线前缀）跨模块导入。
"""

# 默认飞书 chat_id（单用户场景占位，正式部署从配置/用户表取）
DEFAULT_CHAT_ID = "chat_id_placeholder"
