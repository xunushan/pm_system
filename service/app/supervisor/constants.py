"""Supervisor 共享常量。

供 handlers / scheduler 共用，避免私有名（下划线前缀）跨模块导入。
"""

from app.config import settings

# 默认飞书推送目标（单用户场景：个人 open_id 或群 chat_id，从 .env 读取）
DEFAULT_CHAT_ID = settings.feishu_default_chat_id
