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


def _receive_id_type(receive_id: str) -> str:
    """根据 receive_id 前缀推断飞书 receive_id_type（飞书 API 要求与 id 匹配）。

    - ou_ -> open_id（个人）
    - oc_ -> chat_id（群）
    - on_ -> union_id
    其余默认 chat_id（兼容历史调用方传群 chat_id 的情形）。
    """
    if receive_id.startswith("ou_"):
        return "open_id"
    if receive_id.startswith("on_"):
        return "union_id"
    return "chat_id"


class FeishuClient:
    """飞书 API 客户端：发送消息 / 卡片 / 文件。

    所有方法均为外部 HTTP 调用，事务后异步调用（铁律 §3#3）。
    测试时 mock httpx 或整个 client。
    """

    def __init__(self) -> None:
        self.app_id = settings.feishu_app_id
        self.app_secret = settings.feishu_app_secret
        self._token: str | None = None

    def _is_configured(self) -> bool:
        """飞书是否已配置（app_id 非空）。

        未配置时记 warning 并返回 False，调用方应 graceful skip（不调 httpx），
        避免 app_id 为空时仍请求 token API 触发 KeyError（issue #14）。
        """
        if not self.app_id:
            logger.warning("飞书未配置（FEISHU_APP_ID 为空），跳过推送")
            return False
        return True

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
        if not self._is_configured():
            return None
        resp = httpx.post(
            f"{_FEISHU_API}/im/v1/messages",
            headers=self._headers(),
            params={"receive_id_type": _receive_id_type(chat_id)},
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
        if not self._is_configured():
            return None
        resp = httpx.patch(
            f"{_FEISHU_API}/im/v1/messages/{message_id}",
            headers=self._headers(),
            json={"content": _to_json_str(card)},
            timeout=10,
        )
        resp.raise_for_status()

    def send_text(self, chat_id: str, text: str) -> str | None:
        """发送文本消息，返回 message_id。"""
        if not self._is_configured():
            return None
        resp = httpx.post(
            f"{_FEISHU_API}/im/v1/messages",
            headers=self._headers(),
            params={"receive_id_type": _receive_id_type(chat_id)},
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
        if not self._is_configured():
            return None
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
            params={"receive_id_type": _receive_id_type(chat_id)},
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


def build_phase_linking_card(
    completed_phase_name: str,
    next_phase_id: str,
    next_phase_name: str,
    suggested_deadline: str,
    user_id: str = "",
) -> dict:
    """构建阶段衔接卡片（doc/03 §3.3 Step3，模板填充，无 LLM）。

    卡片内容：阶段X已完成 -> 下一阶段Y，deadline date_picker。
    按钮：确认激活 / 暂不激活。
    回调 action_id：story8_确认激活 / story8_暂不激活。
    """
    content = (
        f"✅ **阶段「{completed_phase_name}」已完成**\n\n"
        f"下一阶段：**{next_phase_name}**\n"
        f"建议 deadline：{suggested_deadline}\n\n"
        f"请确认是否激活下一阶段。"
    )
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
                    "text": {"type": "plain_text", "content": "确认激活"},
                    "value": {
                        "action_id": "story8_确认激活",
                        "phase_id": next_phase_id,
                        "deadline": suggested_deadline,
                        "user_id": user_id,
                    },
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "content": "暂不激活"},
                    "value": {
                        "action_id": "story8_暂不激活",
                        "phase_id": next_phase_id,
                        "user_id": user_id,
                    },
                },
            ],
        },
    }


def build_theme_completed_card(
    completed_theme_name: str,
    other_themes: list[dict],
    user_id: str = "",
) -> dict:
    """构建专题完成卡片（doc/03 §3.2，模板填充，无 LLM）。

    卡片内容：专题X已完成 -> 列出同 goal 下未完成的其他专题（单选，专题无序）。
    用户选后跳 Story2 激活（patch 填 deadline）。
    """
    theme_list = (
        "\n".join(f"· {t['name']}（{t['type']}）" for t in other_themes)
        or "（该目标下所有专题均已完成）"
    )
    content = f"🎉 **专题「{completed_theme_name}」已完成**\n\n其他未完成专题：\n{theme_list}"
    actions: list[dict] = []
    for t in other_themes:
        actions.append(
            {
                "type": "button",
                "text": {"type": "plain_text", "content": f"激活：{t['name']}"},
                "value": {
                    "action_id": "story8_去激活",
                    "theme_id": t["theme_id"],
                    "user_id": user_id,
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


def build_goal_completed_card(goal_name: str) -> dict:
    """构建目标完成通知卡片（纯通知，无按钮）。"""
    content = f"🎯 **目标「{goal_name}」已全部完成！**\n\n恭喜达成目标。"
    return {
        "type": "template",
        "data": {
            "template": {
                "type": "column_set",
                "columns": [{"elements": [{"type": "markdown", "content": content}]}],
            },
        },
    }


def build_start_date_reminder_card(
    goal_id: str,
    goal_name: str,
    scheduled_start_date: str,
    user_id: str = "",
) -> dict:
    """构建 scheduled_start_date 到了未激活提醒卡片（doc/06 §I Step4）。"""
    content = (
        f"⏰ **计划开始日提醒**\n\n"
        f"目标：**{goal_name}**\n"
        f"计划开始日：{scheduled_start_date}\n\n"
        f"你计划今天开始，要激活吗？"
    )
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
                    "text": {"type": "plain_text", "content": "去激活"},
                    "value": {
                        "action_id": "story8_去激活",
                        "goal_id": goal_id,
                        "user_id": user_id,
                    },
                }
            ],
        },
    }


def build_deadline_reminder_card(
    phase_id: str,
    phase_name: str,
    deadline: str,
    h5_base_url: str = "",
    user_id: str = "",
) -> dict:
    """构建 deadline 临近提醒卡片（doc/06 §I Step5）。"""
    content = (
        f"📅 **deadline 临近**\n\n"
        f"阶段：**{phase_name}**\n"
        f"deadline：{deadline}\n\n"
        f"请注意进度，及时调整。"
    )
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
                    "text": {"type": "plain_text", "content": "去页面调整"},
                    "value": {
                        "action_id": "story8_去页面调整",
                        "phase_id": phase_id,
                        "user_id": user_id,
                    },
                }
            ],
        },
    }


def build_plan_reminder_card(date_str: str) -> dict:
    """构建未确认计划提醒卡片（doc/06 §I Step6，10:00 巡检）。"""
    content = f"📋 **今日计划未确认**\n\n日期：{date_str}\n\n请尽快确认今日计划。"
    return {
        "type": "template",
        "data": {
            "template": {
                "type": "column_set",
                "columns": [{"elements": [{"type": "markdown", "content": content}]}],
            },
        },
    }


def build_summary_reminder_card(date_str: str) -> dict:
    """构建未做日终总结提醒卡片（doc/06 §I Step7，21:00 巡检）。"""
    content = f"📝 **今日日终总结未完成**\n\n日期：{date_str}\n\n请尽快完成日终总结。"
    return {
        "type": "template",
        "data": {
            "template": {
                "type": "column_set",
                "columns": [{"elements": [{"type": "markdown", "content": content}]}],
            },
        },
    }


def _to_json_str(obj: dict) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False)
