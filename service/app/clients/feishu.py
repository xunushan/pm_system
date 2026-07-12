"""飞书 API 客户端：推送消息 / 发送或更新卡片 / 发送文件。

卡片数据量原则（8.18）：只展示概览，回调只传标识符（draft_id/task_id 等），
细节在 H5 页面。卡片刷新用 message_id 调"更新消息"接口（8.5）。

卡片格式：schema 2.0（``{"schema":"2.0","header":{...},"body":{"elements":[...]}}``），
旧版 config+elements 已废弃（doc/09 V5）。两类按钮（doc/09 通用规则）：
  - form 外回传按钮：``{"tag":"button","behaviors":[{"type":"callback","value":{...}}]}``
    -> Service 从 ``event.action.value.action_id`` 取
  - form 内提交按钮：``{"tag":"button","action_type":"form_submit","name":"<name>"}``
    -> 不带 behaviors（doc/09 V1），Service 从 ``event.action.name`` 取

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


# ===========================================================================
# 卡片 builder（schema 2.0，doc/09 实证规格）
#
# 结构：{"schema":"2.0","header":{...},"body":{"elements":[...]}}
# 两类按钮（doc/09 通用规则）：
#   1. form 外回传：behaviors callback，value 含 action_id（webhook 读 action.value）
#   2. form 内提交：action_type=form_submit，靠 name 区分（webhook 读 action.name）
#      form_submit 按钮不能带 behaviors（doc/09 V1）
# ===========================================================================


def build_verification_card(task_id: str, task_name: str, file_paths: list[str]) -> dict:
    """构建验收卡片（schema 2.0，doc/09 §S4A 场景1）。

    卡片内容：任务名 + 产出文件列表 + form
    （验收通过 btn_pass / input feedback / 需要修改 btn_reject）。
    form_submit 按钮靠 name 区分（btn_pass/btn_reject），不带 behaviors（doc/09 V1）。
    feedback input 收修改建议（issue #20 builder 侧补回）。

    注意：task_id 参数保留签名兼容；form_submit 按钮无 value/behaviors，
    webhook 侧读 form_value + name 路由归 PR-D 收尾。
    """
    file_list = "\n".join(f"· {fp}" for fp in file_paths) or "（无产出文件）"
    content = f"**任务：{task_name}**\n\n**产出文件：**\n{file_list}"
    reject_hint = "**若需修改，请填写反馈后点「需要修改」：**"
    return {
        "schema": "2.0",
        "header": {
            "title": {"tag": "plain_text", "content": "✅ 智能体产出验收"},
            "template": "blue",
        },
        "body": {
            "elements": [
                {"tag": "markdown", "content": content},
                {
                    "tag": "form",
                    "name": "verify_form",
                    "elements": [
                        {
                            "tag": "button",
                            "name": "btn_pass",
                            "text": {"tag": "plain_text", "content": "验收通过"},
                            "type": "primary",
                            "action_type": "form_submit",
                        },
                        {"tag": "hr"},
                        {"tag": "markdown", "content": reject_hint},
                        {
                            "tag": "input",
                            "name": "feedback",
                            "placeholder": {"tag": "plain_text", "content": "输入修改建议"},
                        },
                        {
                            "tag": "button",
                            "name": "btn_reject",
                            "text": {"tag": "plain_text", "content": "需要修改"},
                            "type": "danger",
                            "action_type": "form_submit",
                        },
                    ],
                },
            ]
        },
    }


def build_daily_summary_card(
    daily_id: str,
    date_str: str,
    completed_tasks: list[dict],
    incomplete_tasks: list[dict],
    phase_health: list[dict],
) -> dict:
    """构建日终总结卡片（schema 2.0，doc/09 §S5 状态1）。

    卡片内容：今日任务列表（checker 勾选=已完成）+ 阶段进展 + 确认日终总结按钮。
    每任务一个 checker：已完成任务 checked=true，未完成 checked=false。
    用户调整勾选后点确认，Service 对比初始状态反转变化的任务（doc/09 §S5）。

    注意：daily_id 参数保留签名兼容；form_submit 按钮无 value/behaviors，
    webhook 侧读 form_value（checker 状态）+ name 路由归 PR-D 收尾。
    """
    elements: list[dict] = [
        {"tag": "markdown", "content": "**今日任务：**（勾选=已完成，调整后点确认）"},
    ]

    form_elements: list[dict] = []
    for t in completed_tasks:
        form_elements.append(
            {
                "tag": "checker",
                "name": f"task_{t['task_id']}",
                "text": {"tag": "plain_text", "content": t["name"]},
                "checked": True,
            }
        )
    for t in incomplete_tasks:
        form_elements.append(
            {
                "tag": "checker",
                "name": f"task_{t['task_id']}",
                "text": {"tag": "plain_text", "content": t["name"]},
                "checked": False,
            }
        )

    if phase_health:
        phase_lines = "\n".join(
            f"· {p['name']}：{p['completed']}/{p['total']} {p['status']}"
            f"（{int(p.get('rate', 0) * 100)}%）"
            for p in phase_health
        )
        form_elements.append({"tag": "hr"})
        form_elements.append({"tag": "markdown", "content": f"**阶段进展：**\n{phase_lines}"})

    form_elements.append({"tag": "hr"})
    form_elements.append(
        {
            "tag": "button",
            "name": "confirm_btn",
            "text": {"tag": "plain_text", "content": "确认日终总结"},
            "type": "primary",
            "action_type": "form_submit",
        }
    )

    elements.append({"tag": "form", "name": "daily_summary_form", "elements": form_elements})

    return {
        "schema": "2.0",
        "header": {
            "title": {"tag": "plain_text", "content": f"📊 今日总结（{date_str}）"},
            "template": "blue",
        },
        "body": {"elements": elements},
    }


def build_phase_linking_card(
    completed_phase_name: str,
    next_phase_id: str,
    next_phase_name: str,
    suggested_deadline: str,
    user_id: str = "",
) -> dict:
    """构建阶段衔接卡片（schema 2.0，doc/09 §S8 阶段衔接卡）。

    卡片内容：阶段X已完成 -> 下一阶段Y，date_picker 确认/改 deadline。
    确认激活/暂不激活用 column_set 水平并列（form_submit，靠 name 区分）。

    注意：next_phase_id/user_id 参数保留签名兼容；form_submit 按钮无 value/behaviors，
    webhook 侧读 form_value（date_picker）+ name 路由归 PR-D 收尾。
    """
    content = (
        f"✅ **阶段「{completed_phase_name}」已完成**\n\n"
        f"下一阶段：**{next_phase_name}**\n\n"
        f"请确认 deadline 并激活："
    )
    return {
        "schema": "2.0",
        "header": {
            "title": {"tag": "plain_text", "content": "🎯 阶段衔接"},
            "template": "blue",
        },
        "body": {
            "elements": [
                {"tag": "markdown", "content": content},
                {
                    "tag": "form",
                    "name": "phase_linking_form",
                    "elements": [
                        {
                            "tag": "date_picker",
                            "name": "deadline",
                            "required": True,
                            "placeholder": {"tag": "plain_text", "content": "选 deadline"},
                            "initial_date": suggested_deadline,
                        },
                        {"tag": "hr"},
                        {
                            "tag": "column_set",
                            "columns": [
                                {
                                    "tag": "column",
                                    "width": "weighted",
                                    "weight": 1,
                                    "elements": [
                                        {
                                            "tag": "button",
                                            "name": "btn_activate",
                                            "text": {"tag": "plain_text", "content": "确认激活"},
                                            "type": "primary",
                                            "action_type": "form_submit",
                                        }
                                    ],
                                },
                                {
                                    "tag": "column",
                                    "width": "weighted",
                                    "weight": 1,
                                    "elements": [
                                        {
                                            "tag": "button",
                                            "name": "btn_defer",
                                            "text": {"tag": "plain_text", "content": "暂不激活"},
                                            "type": "default",
                                            "action_type": "form_submit",
                                        }
                                    ],
                                },
                            ],
                        },
                    ],
                },
            ]
        },
    }


def build_theme_completed_card(
    completed_theme_name: str,
    other_themes: list[dict],
    user_id: str = "",
) -> dict:
    """构建专题完成卡片（schema 2.0，doc/09 §S8其他子卡）。

    卡片内容：专题X已完成 -> 列出同 goal 下未完成的其他专题（专题无序，D13）。
    每未完成专题一个「激活此专题」按钮（form 外 behaviors callback）。
    """
    theme_list = (
        "\n".join(f"· {t['name']}（{t['type']}）" for t in other_themes)
        or "（该目标下所有专题均已完成）"
    )
    content = f"🎉 **专题「{completed_theme_name}」已完成**\n\n其他未完成专题：\n{theme_list}"
    elements: list[dict] = [{"tag": "markdown", "content": content}]
    for t in other_themes:
        elements.append(
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": f"激活：{t['name']}"},
                "type": "primary",
                "behaviors": [
                    {
                        "type": "callback",
                        "value": {
                            "action_id": "story8_去激活",
                            "theme_id": t["theme_id"],
                            "user_id": user_id,
                        },
                    }
                ],
            }
        )
    return {
        "schema": "2.0",
        "header": {
            "title": {"tag": "plain_text", "content": "🎉 专题完成"},
            "template": "blue",
        },
        "body": {"elements": elements},
    }


def build_goal_completed_card(goal_name: str) -> dict:
    """构建目标完成通知卡片（schema 2.0，doc/09 §S8其他子卡，纯通知无按钮）。"""
    content = f"🎯 **目标「{goal_name}」已全部完成！**\n\n恭喜达成目标。"
    return {
        "schema": "2.0",
        "header": {
            "title": {"tag": "plain_text", "content": "🎯 目标完成"},
            "template": "green",
        },
        "body": {"elements": [{"tag": "markdown", "content": content}]},
    }


def build_start_date_reminder_card(
    goal_id: str,
    goal_name: str,
    scheduled_start_date: str,
    user_id: str = "",
) -> dict:
    """构建开始日未激活提醒卡片（schema 2.0，doc/06 §I Step4 / doc/09 §S8其他子卡）。

    纯提醒 + 去激活按钮（form 外 behaviors callback）。
    """
    content = (
        f"⏰ **计划开始日提醒**\n\n"
        f"目标：**{goal_name}**\n"
        f"计划开始日：{scheduled_start_date}\n\n"
        f"你计划今天开始，要激活吗？"
    )
    return {
        "schema": "2.0",
        "header": {
            "title": {"tag": "plain_text", "content": "⏰ 计划开始日提醒"},
            "template": "orange",
        },
        "body": {
            "elements": [
                {"tag": "markdown", "content": content},
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "去激活"},
                    "type": "primary",
                    "behaviors": [
                        {
                            "type": "callback",
                            "value": {
                                "action_id": "story8_去激活",
                                "goal_id": goal_id,
                                "user_id": user_id,
                            },
                        }
                    ],
                },
            ]
        },
    }


def build_deadline_reminder_card(
    phase_id: str,
    phase_name: str,
    deadline: str,
    h5_base_url: str = "",
    user_id: str = "",
) -> dict:
    """构建 deadline 临近提醒卡片（schema 2.0，doc/06 §I Step5 / doc/09 §S8其他子卡）。

    纯提醒 + 去页面调整按钮（form 外 behaviors callback）。
    """
    content = (
        f"📅 **deadline 临近**\n\n"
        f"阶段：**{phase_name}**\n"
        f"deadline：{deadline}\n\n"
        f"请注意进度，及时调整。"
    )
    return {
        "schema": "2.0",
        "header": {
            "title": {"tag": "plain_text", "content": "📅 deadline 临近"},
            "template": "orange",
        },
        "body": {
            "elements": [
                {"tag": "markdown", "content": content},
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "去页面调整"},
                    "type": "primary",
                    "behaviors": [
                        {
                            "type": "callback",
                            "value": {
                                "action_id": "story8_去页面调整",
                                "phase_id": phase_id,
                                "user_id": user_id,
                            },
                        }
                    ],
                },
            ]
        },
    }


def build_plan_reminder_card(date_str: str) -> dict:
    """构建未确认计划提醒卡片（schema 2.0，doc/06 §I Step6，10:00 巡检）。"""
    content = f"📋 **今日计划未确认**\n\n日期：{date_str}\n\n请尽快确认今日计划。"
    return {
        "schema": "2.0",
        "header": {
            "title": {"tag": "plain_text", "content": "📋 今日计划未确认"},
            "template": "orange",
        },
        "body": {"elements": [{"tag": "markdown", "content": content}]},
    }


def build_summary_reminder_card(date_str: str) -> dict:
    """构建未做日终总结提醒卡片（schema 2.0，doc/06 §I Step7，21:00 巡检）。"""
    content = f"📝 **今日日终总结未完成**\n\n日期：{date_str}\n\n请尽快完成日终总结。"
    return {
        "schema": "2.0",
        "header": {
            "title": {"tag": "plain_text", "content": "📝 日终总结未完成"},
            "template": "orange",
        },
        "body": {"elements": [{"tag": "markdown", "content": content}]},
    }


def _to_json_str(obj: dict) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False)
