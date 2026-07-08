"""飞书 API 客户端：推送消息 / 发送或更新卡片 / 发送文件。

卡片数据量原则（8.18）：只展示概览，回调只传标识符（draft_id/task_id 等），
细节在 H5 页面。卡片刷新用 message_id 调"更新消息"接口（8.5）。
TODO(各 Story)：用 httpx 实现，token 走飞书开放平台 tenant_access_token。
"""

from app.config import settings


class FeishuClient:
    """TODO：实现 send_message / update_card / send_file / get_token。"""

    def __init__(self) -> None:
        self.app_id = settings.feishu_app_id
        self.app_secret = settings.feishu_app_secret
