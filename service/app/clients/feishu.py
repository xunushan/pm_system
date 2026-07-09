"""飞书 API 客户端：推送消息 / 发送或更新卡片 / 发送文件。

卡片数据量原则（8.18）：只展示概览，回调只传标识符（draft_id/task_id 等），
细节在 H5 页面。卡片刷新用 message_id 调"更新消息"接口（8.5）。

用 httpx 实现，token 走飞书开放平台 tenant_access_token。
外部 HTTP 调用，测试 mock httpx（不真连飞书）。
"""

import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_FEISHU_API = "https://open.feishu.cn/open-apis"


class FeishuClient:
    """飞书 API 客户端：发送消息 / 卡片 / 文件。

    所有方法均为外部 HTTP 调用，事务后异步调用（铁律 §3#3）。
    测试时 mock httpx 或整个 client。
    """

    def __init__(self) -> None:
        self.app_id = settings.feishu_app_id
        self.app_secret = settings.feishu_app_secret
        self._token: str | None = None

    def _get_token(self) -> str:
        """获取 tenant_access_token（缓存简单实现）。"""
        if self._token:
            return self._token
        resp = httpx.post(
            f"{_FEISHU_API}/auth/v3/tenant_access_token/internal",
            json={"app_id": self.app_id, "app_secret": self.app_secret},
            timeout=10,
        )
        resp.raise_for_status()
        self._token = resp.json()["tenant_access_token"]
        return self._token

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._get_token()}"}

    def send_card(self, chat_id: str, card: dict) -> str | None:
        """发送交互卡片，返回 message_id。"""
        resp = httpx.post(
            f"{_FEISHU_API}/im/v1/messages",
            headers=self._headers(),
            params={"receive_id_type": "chat_id"},
            json={
                "receive_id": chat_id,
                "msg_type": "interactive",
                "content": _to_json_str(card),
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("data", {}).get("message_id")

    def update_card(self, message_id: str, card: dict) -> None:
        """更新已发送的卡片（8.5）。"""
        resp = httpx.patch(
            f"{_FEISHU_API}/im/v1/messages/{message_id}",
            headers=self._headers(),
            json={"content": _to_json_str(card)},
            timeout=10,
        )
        resp.raise_for_status()

    def send_text(self, chat_id: str, text: str) -> str | None:
        """发送文本消息，返回 message_id。"""
        resp = httpx.post(
            f"{_FEISHU_API}/im/v1/messages",
            headers=self._headers(),
            params={"receive_id_type": "chat_id"},
            json={
                "receive_id": chat_id,
                "msg_type": "text",
                "content": _to_json_str({"text": text}),
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("data", {}).get("message_id")

    def send_file(self, chat_id: str, file_path: str) -> str | None:
        """发送文件消息（逐个发送产出文件到飞书，doc/06 步骤6）。"""
        # 先上传文件获取 file_key
        import os

        filename = os.path.basename(file_path)
        with open(file_path, "rb") as f:
            upload_resp = httpx.post(
                f"{_FEISHU_API}/im/v1/files",
                headers=self._headers(),
                data={"file_type": "stream", "file_name": filename},
                files={"file": (filename, f)},
                timeout=30,
            )
        upload_resp.raise_for_status()
        file_key = upload_resp.json().get("data", {}).get("file_key")
        if not file_key:
            return None

        # 再发文件消息
        resp = httpx.post(
            f"{_FEISHU_API}/im/v1/messages",
            headers=self._headers(),
            params={"receive_id_type": "chat_id"},
            json={
                "receive_id": chat_id,
                "msg_type": "file",
                "content": _to_json_str({"file_key": file_key}),
            },
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json().get("data", {}).get("message_id")


def build_verification_card(task_id: str, task_name: str, file_paths: list[str]) -> dict:
    """构建验收卡片（模板填充，无 LLM，doc/06 步骤6）。

    卡片内容：任务名 + 产出文件名列表 + 验收通过/需要修改按钮。
    回调 action_id：story4A_验收通过 / story4A_需要修改（带 feedback 输入框）。
    """
    file_list = "\n".join(f"· {fp}" for fp in file_paths) or "（无产出文件）"
    content = f"📋 **任务完成确认**\n\n任务：{task_name}\n\n产出文件：\n{file_list}"
    return {
        "type": "template",
        "data": {
            "template": {
                "type": "column_set",
                "columns": [{"elements": [{"type": "markdown", "content": content}]}],
            },
            "actions": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "content": "验收通过"},
                    "value": {"action_id": "story4A_验收通过", "task_id": task_id},
                },
                {
                    "type": "input",
                    "placeholder": {"type": "plain_text", "content": "输入修改意见"},
                    "name": "feedback",
                    "actions": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "content": "需要修改"},
                            "value": {"action_id": "story4A_需要修改", "task_id": task_id},
                        }
                    ],
                },
            ],
        },
    }


def build_daily_summary_card(
    daily_id: str,
    date_str: str,
    completed_tasks: list[dict],
    incomplete_tasks: list[dict],
    phase_health: list[dict],
) -> dict:
    """构建日终总结卡片（模板填充，无 LLM，doc/06 步骤4）。

    卡片内容：今日任务列表（每项带状态切换按钮）+ 步骤进展 + 确认日终总结按钮。
    异议双向按钮（doc/01 S5 + D18）：
      - 已完成 -> 显示[标记未完成]按钮
      - 未完成 -> 显示[标记完成]按钮
    """
    lines: list[str] = [f"📊 **今日总结（{date_str}）**\n"]

    # 今日任务
    lines.append("**今日任务：**")
    for t in completed_tasks:
        lines.append(f"· {t['name']} ✅  [标记未完成]")
    for t in incomplete_tasks:
        lines.append(f"· {t['name']} ❌  [标记完成]")

    # 阶段进展
    if phase_health:
        lines.append("\n**步骤进展：**")
        for p in phase_health:
            pct = int(p.get("rate", 0) * 100)
            lines.append(f"· {p['name']} {p['completed']}/{p['total']} {p['status']}（{pct}%）")

    content = "\n".join(lines)

    # 按钮列表：每个任务一个状态切换按钮
    actions: list[dict] = []
    for t in completed_tasks:
        actions.append(
            {
                "type": "button",
                "text": {"type": "plain_text", "content": f"标记未完成：{t['name']}"},
                "value": {
                    "action_id": "story5_标记未完成",
                    "task_id": t["task_id"],
                    "daily_id": daily_id,
                    "user_id": "",
                },
            }
        )
    for t in incomplete_tasks:
        actions.append(
            {
                "type": "button",
                "text": {"type": "plain_text", "content": f"标记完成：{t['name']}"},
                "value": {
                    "action_id": "story5_标记完成",
                    "task_id": t["task_id"],
                    "daily_id": daily_id,
                    "user_id": "",
                },
            }
        )
    # 确认日终总结按钮
    actions.append(
        {
            "type": "button",
            "text": {"type": "plain_text", "content": "确认日终总结"},
            "value": {
                "action_id": "story5_确认日终总结",
                "daily_id": daily_id,
                "user_id": "",
            },
        }
    )

    return {
        "type": "template",
        "data": {
            "template": {
                "type": "column_set",
                "columns": [{"elements": [{"type": "markdown", "content": content}]}],
            },
            "actions": actions,
        },
    }


def _to_json_str(obj: dict) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False)
