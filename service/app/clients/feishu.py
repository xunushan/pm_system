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


def _executor_tag(executor: str) -> str:
    """映射 executor 标识到飞书显示标签（doc/09 §S3/S4A）。

    - ``human`` -> ``[人]``
    - ``agent`` -> ``[智能体]``
    - 已含方括号的（如 ``[人]``）原样返回
    - 其余按 ``[{executor}]`` 包装
    """
    if executor.startswith("["):
        return executor
    return {"human": "[人]", "agent": "[智能体]"}.get(executor, f"[{executor}]")


def build_plan_overview_card(
    goal_name: str,
    theme_count: int,
    phase_count: int,
    task_count: int,
    draft_id: str,
) -> dict:
    """构建方案总览卡片-确认前（schema 2.0，doc/09 §S1 确认前）。

    无 form，纯 markdown 概览 + 确认方案按钮（form 外 behaviors callback）。
    回传 action_id=story1_确认方案 + draft_id。

    :param goal_name: 目标名称
    :param theme_count: 专题数
    :param phase_count: 阶段数
    :param task_count: 任务数
    :param draft_id: 草稿 ID（确认按钮回传，Service 据此读 draft 落库）
    """
    content = (
        f"**目标：{goal_name}**\n\n"
        f"专题数：{theme_count}\n"
        f"阶段数：{phase_count}\n"
        f"任务数：{task_count}\n\n"
        f"确认后将正式建库，可在 H5 页面调整。"
    )
    return {
        "schema": "2.0",
        "header": {
            "title": {"tag": "plain_text", "content": "📋 方案总览"},
            "template": "blue",
        },
        "body": {
            "elements": [
                {"tag": "markdown", "content": content},
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "确认方案"},
                    "type": "primary",
                    "behaviors": [
                        {
                            "type": "callback",
                            "value": {
                                "action_id": "story1_确认方案",
                                "draft_id": draft_id,
                            },
                        }
                    ],
                },
            ]
        },
    }


def build_schedule_card_a(
    goal_name: str,
    themes: list[dict],
    h5_url: str = "",
) -> dict:
    """构建调度激活卡片 A-选专题（schema 2.0，doc/09 §S2 状态1）。

    form + 每个专题一个 checker 勾选框 + 下一步按钮（form_submit，name=next_btn）。
    用户勾选专题后 Service update_card 刷成卡片 B（填 deadline）。

    :param goal_name: 目标名称
    :param themes: 专题列表，每项含 ``theme_id``/``name``/``type``
    :param h5_url: H5 配置页链接（可选，不传则纯文字提示）
    """
    form_elements: list[dict] = []
    for t in themes:
        form_elements.append(
            {
                "tag": "checker",
                "name": f"theme_{t['theme_id']}",
                "text": {"tag": "plain_text", "content": f"{t['name']}（{t['type']}）"},
            }
        )
    form_elements.append(
        {
            "tag": "button",
            "name": "next_btn",
            "text": {"tag": "plain_text", "content": "下一步"},
            "type": "primary",
            "action_type": "form_submit",
        }
    )

    elements: list[dict] = [
        {"tag": "markdown", "content": f"**目标：{goal_name}**\n\n请勾选要激活的专题："},
        {"tag": "form", "name": "schedule_form_a", "elements": form_elements},
        {"tag": "hr"},
    ]
    if h5_url:
        elements.append(
            {
                "tag": "markdown",
                "content": f"默认全托管，调整 managed/path 请[前往配置页]({h5_url})",
            }
        )
    else:
        elements.append(
            {"tag": "markdown", "content": "默认全托管，调整 managed/path 请前往配置页"}
        )

    return {
        "schema": "2.0",
        "header": {
            "title": {"tag": "plain_text", "content": "🎯 调度激活"},
            "template": "blue",
        },
        "body": {"elements": elements},
    }


def build_schedule_card_b(
    goal_name: str,
    phases: list[dict],
) -> dict:
    """构建调度激活卡片 B-填 deadline（schema 2.0，doc/09 §S2 状态2）。

    form + 每个激活阶段一个 div（阶段名）+ date_picker + 确认调度按钮（form_submit，
    name=confirm_btn）。patch 卡 A->B 是两态（A 选专题后 update_card 刷成 B）。

    :param goal_name: 目标名称
    :param phases: 激活阶段列表，每项含 ``theme_id``/``theme_name``/``phase_name``/``type``
    """
    form_elements: list[dict] = []
    for p in phases:
        form_elements.append(
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"· **{p['theme_name']} / {p['phase_name']}**（{p['type']}）",
                },
            }
        )
        form_elements.append(
            {
                "tag": "date_picker",
                "name": f"dl_theme_{p['theme_id']}",
                "required": True,
                "placeholder": {"tag": "plain_text", "content": "选 deadline"},
            }
        )
    form_elements.append(
        {
            "tag": "button",
            "name": "confirm_btn",
            "text": {"tag": "plain_text", "content": "确认调度"},
            "type": "primary",
            "action_type": "form_submit",
        }
    )

    return {
        "schema": "2.0",
        "header": {
            "title": {"tag": "plain_text", "content": "🎯 调度激活 - 填 deadline"},
            "template": "blue",
        },
        "body": {
            "elements": [
                {
                    "tag": "markdown",
                    "content": f"**目标：{goal_name}**\n\n以下阶段将被激活，请填 deadline：",
                },
                {"tag": "form", "name": "schedule_form_b", "elements": form_elements},
            ]
        },
    }


def build_daily_plan_card(
    date_str: str,
    candidate_tasks: list[dict],
    prerequisites: list[dict],
) -> dict:
    """构建今日计划卡片（schema 2.0，doc/09 §S3 状态1）。

    form + checker 两组：候选任务勾选（勾选=今日要做）+ 前置任务勾选（可取消）。
    两组独立（铁律 §9 前置整体/与任务解耦）。确认今日计划按钮（form_submit，name=confirm_btn）。

    :param date_str: 日期字符串（如 ``2026-07-10``）
    :param candidate_tasks: 候选任务列表，每项含 ``task_id``/``name``/``executor``，
        可选 ``phase_info``（如 ``知识获取/阶段1``，显示在任务名后的括号里）
    :param prerequisites: 前置列表，每项含 ``subtask_id``/``name``
    """
    form_elements: list[dict] = []

    # 候选任务 checker
    for t in candidate_tasks:
        executor_tag = _executor_tag(t["executor"])
        phase_info = t.get("phase_info")
        if phase_info:
            text = f"{t['name']}（{phase_info}）{executor_tag}"
        else:
            text = f"{t['name']} {executor_tag}"
        form_elements.append(
            {
                "tag": "checker",
                "name": f"task_{t['task_id']}",
                "text": {"tag": "plain_text", "content": text},
            }
        )

    # 前置 checker（独立一组，与任务解耦，铁律 §9）
    if prerequisites:
        form_elements.append({"tag": "hr"})
        form_elements.append({"tag": "markdown", "content": "**今日前置：**（可取消）"})
        for p in prerequisites:
            form_elements.append(
                {
                    "tag": "checker",
                    "name": f"pre_{p['subtask_id']}",
                    "text": {"tag": "plain_text", "content": p["name"]},
                }
            )

    form_elements.append({"tag": "hr"})
    form_elements.append(
        {
            "tag": "button",
            "name": "confirm_btn",
            "text": {"tag": "plain_text", "content": "确认今日计划"},
            "type": "primary",
            "action_type": "form_submit",
        }
    )

    return {
        "schema": "2.0",
        "header": {
            "title": {"tag": "plain_text", "content": f"📋 今日计划（{date_str}）"},
            "template": "blue",
        },
        "body": {
            "elements": [
                {"tag": "markdown", "content": "**候选任务：**（勾选今日要做的）"},
                {"tag": "form", "name": "daily_plan_form", "elements": form_elements},
            ]
        },
    }


def build_task_complete_card(
    workspace_name: str,
    completed_tasks: list[dict],
    pending_tasks: list[dict],
) -> dict:
    """构建确认完成任务卡片（schema 2.0，doc/09 §S4A 场景4，D26 新增）。

    已完成任务：纯展示（div + lark_md，不可操作），显示执行主体 [人]/[智能体]。
    待确认任务：checker 勾选确认完成（name=task_<id>），显示执行主体。
    智能体任务可选"改交智能体重新执行"checker（name=task_<id>_reassign），文案带缩进箭头。
    reassign 与 confirm 互斥（builder 只渲染两个 checker，互斥判定在 webhook/Service PR-D）。
    确认完成按钮（form_submit，name=confirm_btn）。

    :param workspace_name: 工作空间名称
    :param completed_tasks: 已完成任务列表，每项含 ``name``/``executor``
    :param pending_tasks: 待确认任务列表，每项含 ``id``/``name``/``executor``/``is_agent``
    """
    elements: list[dict] = [
        {
            "tag": "markdown",
            "content": f"**工作空间：{workspace_name}**\n\n请确认以下任务的完成情况。",
        },
    ]

    # 已完成任务（纯展示，div lark_md，不可操作）
    elements.append({"tag": "markdown", "content": "**✅ 已完成任务：**"})
    if completed_tasks:
        for t in completed_tasks:
            executor_tag = _executor_tag(t["executor"])
            elements.append(
                {
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": f"· {t['name']} {executor_tag}"},
                }
            )
    else:
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": "· （无）"}})

    elements.append({"tag": "hr"})

    # 待确认任务（checker 勾选）
    elements.append({"tag": "markdown", "content": "**⏳ 待确认完成（勾选后点确认）：**"})

    form_elements: list[dict] = []
    for t in pending_tasks:
        executor_tag = _executor_tag(t["executor"])
        form_elements.append(
            {
                "tag": "checker",
                "name": f"task_{t['id']}",
                "text": {"tag": "plain_text", "content": f"{t['name']} {executor_tag}"},
            }
        )
        # 智能体任务可选 reassign（doc/09 §S4A 实现注意：只对 is_agent 任务出现）
        if t.get("is_agent"):
            form_elements.append(
                {
                    "tag": "checker",
                    "name": f"task_{t['id']}_reassign",
                    "text": {
                        "tag": "plain_text",
                        "content": (
                            "    ↑ 将此任务改交智能体重新执行（确认后 executor=智能体，重新下发）"
                        ),
                    },
                }
            )

    form_elements.append({"tag": "hr"})
    form_elements.append(
        {
            "tag": "button",
            "name": "confirm_btn",
            "text": {"tag": "plain_text", "content": "确认完成"},
            "type": "primary",
            "action_type": "form_submit",
        }
    )

    elements.append({"tag": "form", "name": "confirm_complete_form", "elements": form_elements})

    return {
        "schema": "2.0",
        "header": {
            "title": {"tag": "plain_text", "content": "确认完成任务"},
            "template": "blue",
        },
        "body": {"elements": elements},
    }


def build_weekly_summary_card(
    week: str,
    start_date: str,
    end_date: str,
    completed_tasks: list[dict],
    daily_trends: list[dict],
    phase_health: list[dict],
    agent_output_count: int,
    next_week_advice: str,
) -> dict:
    """构建周总结卡片（schema 2.0，doc/09 §S6 状态1）。

    纯展示（无 form）+ 已阅按钮（form 外 behaviors callback，action_id=story6_已阅周总结）。
    必须含本周完成任务列表（用户反馈：只有数字不够，要具体任务名+执行主体+日期）。
    不含子任务统计（子任务不进周总结）。下周建议由 pm-summary LLM 生成（builder 不调 LLM）。

    :param week: 周标识（如 ``2026-W28``）
    :param start_date: 周开始日期
    :param end_date: 周结束日期
    :param completed_tasks: 本周完成任务列表，每项含 ``date``/``task_name``/``executor``
    :param daily_trends: 每日完成趋势，每项含 ``date``/``weekday``/``completed``/``total``
    :param phase_health: 阶段健康度，每项含 ``name``/``completed``/``total``/``status``
    :param agent_output_count: 智能体产出文件数
    :param next_week_advice: 下周建议（pm-summary LLM 生成，builder 不调 LLM）
    """
    elements: list[dict] = [
        {"tag": "markdown", "content": f"**日期范围：** {start_date} ~ {end_date}"},
        {"tag": "hr"},
    ]

    # 本周完成任务列表（必须含，用户反馈）
    if completed_tasks:
        task_lines = "\n".join(
            f"· {t['date']} {t['task_name']} {_executor_tag(t['executor'])}"
            for t in completed_tasks
        )
    else:
        task_lines = "· （本周无完成任务）"
    elements.append({"tag": "markdown", "content": f"**本周完成任务：**\n{task_lines}"})
    elements.append({"tag": "hr"})

    # 每日完成趋势
    if daily_trends:
        trend_lines = "\n".join(
            f"· {d['date']} {d['weekday']}：{d['completed']}/{d['total']}" for d in daily_trends
        )
    else:
        trend_lines = "· （无数据）"
    elements.append({"tag": "markdown", "content": f"**每日完成趋势：**\n{trend_lines}"})
    elements.append({"tag": "hr"})

    # 阶段健康度
    if phase_health:
        health_lines = "\n".join(
            f"· {p['name']}：{p['completed']}/{p['total']} {p['status']}" for p in phase_health
        )
    else:
        health_lines = "· （无数据）"
    elements.append({"tag": "markdown", "content": f"**阶段健康度：**\n{health_lines}"})
    elements.append({"tag": "hr"})

    # 智能体产出
    elements.append({"tag": "markdown", "content": f"**智能体产出：** {agent_output_count} 个文件"})
    elements.append({"tag": "hr"})

    # 下周建议（LLM 生成，参数传入）
    elements.append({"tag": "markdown", "content": f"**下周建议：** {next_week_advice}"})
    elements.append({"tag": "hr"})

    # 已阅按钮（form 外 behaviors callback）
    elements.append(
        {
            "tag": "button",
            "text": {"tag": "plain_text", "content": "已阅"},
            "type": "primary",
            "behaviors": [
                {
                    "type": "callback",
                    "value": {
                        "action_id": "story6_已阅周总结",
                        "week": week,
                    },
                }
            ],
        }
    )

    return {
        "schema": "2.0",
        "header": {
            "title": {"tag": "plain_text", "content": f"📊 周总结（{week}）"},
            "template": "blue",
        },
        "body": {"elements": elements},
    }


def build_post_confirm_card(
    task_name: str,
    task_id: str,
    post_subtasks: list[dict],
    select_all: bool | None = None,
) -> dict:
    """构建后置确认卡片（schema 2.0，doc/09 §S4B 状态1）。

    卡片内容：任务名 + form（checker 后置勾选，默认全选 checked=true）+
    全选/全不选小按钮（form 外 behaviors callback，点了 Service update_card 刷新 checker）+
    确认按钮（form_submit，name=confirm_btn）。

    :param task_name: 任务名称
    :param task_id: 任务 ID（全选/全不选按钮回传）
    :param post_subtasks: 后置列表，每项含 ``id``/``name``
    :param select_all: 全选/全不选切换。None=默认全选（初始推送），
        True=全选（update_card 刷新），False=全不选（update_card 刷新）。
        用于全选/全不选按钮点击后 Service 重建卡片刷新 checker 状态（doc/09 §S4B）。
    """
    form_elements: list[dict] = []
    # select_all=None -> 默认全选（初始推送）；True/False -> 切换后重建（update_card 刷新）
    checked = True if select_all is None else select_all
    for p in post_subtasks:
        form_elements.append(
            {
                "tag": "checker",
                "name": f"post_{p['id']}",
                "text": {"tag": "plain_text", "content": p["name"]},
                "checked": checked,
            }
        )
    form_elements.append({"tag": "hr"})
    form_elements.append(
        {
            "tag": "column_set",
            "columns": [
                {
                    "tag": "column",
                    "width": "auto",
                    "elements": [
                        {
                            "tag": "button",
                            "name": "btn_select_all",
                            "text": {"tag": "plain_text", "content": "全选"},
                            "type": "default",
                            "size": "small",
                            "behaviors": [
                                {
                                    "type": "callback",
                                    "value": {"action_id": "story4B_全选", "task_id": task_id},
                                }
                            ],
                        }
                    ],
                },
                {
                    "tag": "column",
                    "width": "auto",
                    "elements": [
                        {
                            "tag": "button",
                            "name": "btn_unselect_all",
                            "text": {"tag": "plain_text", "content": "全不选"},
                            "type": "default",
                            "size": "small",
                            "behaviors": [
                                {
                                    "type": "callback",
                                    "value": {"action_id": "story4B_全不选", "task_id": task_id},
                                }
                            ],
                        }
                    ],
                },
            ],
        }
    )
    form_elements.append(
        {
            "tag": "button",
            "name": "confirm_btn",
            "text": {"tag": "plain_text", "content": "确认"},
            "type": "primary",
            "action_type": "form_submit",
        }
    )
    return {
        "schema": "2.0",
        "header": {
            "title": {"tag": "plain_text", "content": "✅ 任务已完成"},
            "template": "blue",
        },
        "body": {
            "elements": [
                {
                    "tag": "markdown",
                    "content": (
                        f"**任务：{task_name}**\n\n"
                        "任务已完成。请确认后置收尾项（取消不需要的，可全取消）："
                    ),
                },
                {"tag": "form", "name": "post_confirm_form", "elements": form_elements},
            ]
        },
    }


def build_done_card(title: str, template: str, elements: list[dict]) -> dict:
    """构建终态卡片（schema 2.0，无按钮展示卡，doc/09 各 Story 终态）。

    用于 update_card 刷新：回调业务执行后，重建终态卡刷新原卡片。
    飞书不自动置灰/移除按钮，Service 收回调后必须 update_card（doc/09 §通用规则）。
    终态卡 = 去掉按钮 + 标题转色（green=已完成 / orange=暂缓）+ 确认文案。

    :param title: 卡片标题
    :param template: 标题颜色（green/orange/blue/red）
    :param elements: body 元素列表（markdown/div/hr 等，由调用方构造）
    """
    return {
        "schema": "2.0",
        "header": {"title": {"tag": "plain_text", "content": title}, "template": template},
        "body": {"elements": elements},
    }


def _to_json_str(obj: dict) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False)
