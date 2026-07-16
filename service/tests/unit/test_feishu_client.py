"""Story8/通用 单元测试：FeishuClient（mock httpx，不真连飞书）。

重点覆盖 issue #14：app_id 为空时所有推送方法 graceful skip（不调 httpx），
避免请求 token API 触发 KeyError: 'tenant_access_token'。

另含 15 个 build_*_card schema 2.0 结构校验测试（doc/09 实证规格）：
  PR-A 9 个现有 builder + PR-B 6 个新 builder。
"""

from unittest.mock import MagicMock, patch

from app.clients.feishu import (
    FeishuClient,
    build_daily_plan_card,
    build_daily_summary_card,
    build_deadline_reminder_card,
    build_goal_completed_card,
    build_phase_linking_card,
    build_plan_overview_card,
    build_plan_reminder_card,
    build_schedule_card_a,
    build_schedule_card_b,
    build_start_date_reminder_card,
    build_summary_reminder_card,
    build_task_complete_card,
    build_theme_completed_card,
    build_verification_card,
    build_weekly_summary_card,
)


def _make_client(app_id: str = "") -> FeishuClient:
    """构造 FeishuClient 并显式设置 app_id/app_secret（隔离全局 settings）。"""
    client = FeishuClient()
    client.app_id = app_id
    client.app_secret = "secret" if app_id else ""
    client._token = None
    return client


def _mock_resp() -> MagicMock:
    """构造一个成功的 httpx 响应 mock。"""
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"data": {"message_id": "msg_123", "file_key": "fk_1"}}
    return resp


def test_is_configured_false_when_app_id_empty():
    """app_id 为空 -> _is_configured 返回 False。"""
    client = _make_client(app_id="")
    assert client._is_configured() is False


def test_is_configured_true_when_app_id_set():
    """app_id 非空 -> _is_configured 返回 True。"""
    client = _make_client(app_id="cli_test")
    assert client._is_configured() is True


def test_send_card_skips_http_when_not_configured():
    """issue #14：app_id 为空时 send_card 不调 httpx，返回 None。"""
    client = _make_client(app_id="")
    with patch("app.clients.feishu.httpx.post") as mock_post:
        result = client.send_card("chat_1", {"type": "template"})
    assert result is None
    mock_post.assert_not_called()


def test_send_text_skips_http_when_not_configured():
    """issue #14：app_id 为空时 send_text 不调 httpx，返回 None。"""
    client = _make_client(app_id="")
    with patch("app.clients.feishu.httpx.post") as mock_post:
        result = client.send_text("chat_1", "hello")
    assert result is None
    mock_post.assert_not_called()


def test_update_card_skips_http_when_not_configured():
    """issue #14：app_id 为空时 update_card 不调 httpx。"""
    client = _make_client(app_id="")
    with patch("app.clients.feishu.httpx.patch") as mock_patch:
        result = client.update_card("msg_1", {"type": "template"})
    assert result is None
    mock_patch.assert_not_called()


def test_send_file_skips_http_when_not_configured(tmp_path):
    """issue #14：app_id 为空时 send_file 不调 httpx（即使文件存在），返回 None。"""
    fp = tmp_path / "out.txt"
    fp.write_text("x")
    client = _make_client(app_id="")
    with patch("app.clients.feishu.httpx.post") as mock_post:
        result = client.send_file("chat_1", str(fp))
    assert result is None
    mock_post.assert_not_called()


def test_send_card_calls_http_when_configured():
    """正向用例：app_id 非空时 send_card 正常调 httpx（guard 不阻断正常流程）。"""
    client = _make_client(app_id="cli_test")
    # _get_token 也会调 httpx.post，所以两次 post（token + 发消息）
    token_resp = MagicMock()
    token_resp.raise_for_status = MagicMock()
    token_resp.json.return_value = {"tenant_access_token": "t_xxx"}

    msg_resp = MagicMock()
    msg_resp.raise_for_status = MagicMock()
    msg_resp.json.return_value = {"data": {"message_id": "msg_abc"}}

    with patch("app.clients.feishu.httpx.post", side_effect=[token_resp, msg_resp]) as mock_post:
        result = client.send_card("chat_1", {"type": "template"})

    assert result == "msg_abc"
    assert mock_post.call_count == 2


def test_send_text_calls_http_when_configured():
    """正向用例：app_id 非空时 send_text 正常调 httpx。"""
    client = _make_client(app_id="cli_test")
    token_resp = MagicMock()
    token_resp.raise_for_status = MagicMock()
    token_resp.json.return_value = {"tenant_access_token": "t_xxx"}

    msg_resp = MagicMock()
    msg_resp.raise_for_status = MagicMock()
    msg_resp.json.return_value = {"data": {"message_id": "msg_txt"}}

    with patch("app.clients.feishu.httpx.post", side_effect=[token_resp, msg_resp]) as mock_post:
        result = client.send_text("chat_1", "hello")

    assert result == "msg_txt"
    assert mock_post.call_count == 2


def test_get_token_cached_after_first_call():
    """_get_token 缓存：第二次调用不重复请求 token API。"""
    client = _make_client(app_id="cli_test")
    token_resp = MagicMock()
    token_resp.raise_for_status = MagicMock()
    token_resp.json.return_value = {"tenant_access_token": "t_cached"}

    with patch("app.clients.feishu.httpx.post", return_value=token_resp) as mock_post:
        t1 = client._get_token()
        t2 = client._get_token()

    assert t1 == "t_cached"
    assert t2 == "t_cached"
    # token API 只调一次（缓存命中）
    assert mock_post.call_count == 1


# ---------------------------------------------------------------------------
# 卡片结构校验测试（schema 2.0，doc/09 实证规格）
#
# 新格式（正确）：顶层 {"schema":"2.0","header":{...},"body":{"elements":[...]}}
#   -> 飞书实测推送成功 HTTP 200 code 0（doc/09）
# 旧格式（错误）：顶层 config + elements，不支持 form/checker/date_picker（doc/09 V5）
#
# 以下测试直接断言 builder 返回的 dict 结构，不 mock httpx。
# ---------------------------------------------------------------------------


def _assert_schema2(card: dict):
    """通用断言：schema 2.0 卡片结构。

    - 顶层有 ``schema``=="2.0" + ``header`` + ``body``
    - 无 ``config`` / ``elements``（旧版废弃，doc/09 V5）
    - header 有 title（plain_text）+ template
    - body.elements 非空
    """
    assert card.get("schema") == "2.0", "卡片缺 schema=2.0"
    assert "header" in card, "卡片缺 header"
    assert "body" in card, "卡片缺 body"
    assert "config" not in card, "卡片不应有 config（旧版废弃）"
    assert "elements" not in card, "卡片不应有顶层 elements（旧版废弃）"

    header = card["header"]
    assert header["title"]["tag"] == "plain_text", "header.title 应为 plain_text"
    assert "template" in header, "header 缺 template（颜色）"

    elements = card["body"]["elements"]
    assert len(elements) >= 1, "body.elements 不能为空"


def _find_form(card: dict) -> dict | None:
    """在 body.elements 中找 form 容器，返回第一个 form dict 或 None。"""
    for el in card["body"]["elements"]:
        if el.get("tag") == "form":
            return el
    return None


def _find_buttons(card: dict) -> list[dict]:
    """在 body.elements 中收集所有 button（form 外，非 form 内）。"""
    buttons = []
    for el in card["body"]["elements"]:
        if el.get("tag") == "button":
            buttons.append(el)
    return buttons


def _assert_form_submit_button(btn: dict, expected_name: str):
    """断言 form_submit 按钮：有 name，有 action_type=form_submit，无 behaviors（doc/09 V1）。"""
    assert btn["tag"] == "button", "form_submit 按钮应 tag=button"
    assert btn.get("name") == expected_name, f"form_submit 按钮应为 name={expected_name}"
    assert btn.get("action_type") == "form_submit", "form_submit 按钮应有 action_type=form_submit"
    assert "behaviors" not in btn, "form_submit 按钮不能带 behaviors（doc/09 V1）"
    assert btn["text"]["tag"] == "plain_text", "按钮文本应为 plain_text"


def _assert_callback_button(btn: dict):
    """断言 form 外回调按钮：有 behaviors callback，value 含 action_id（doc/09 通用规则）。"""
    assert btn["tag"] == "button", "回调按钮应 tag=button"
    assert "behaviors" in btn, "form 外按钮应有 behaviors"
    behavior = btn["behaviors"][0]
    assert behavior["type"] == "callback", "behaviors 应为 callback 类型"
    assert "action_id" in behavior["value"], "回调 value 缺 action_id"
    assert btn["text"]["tag"] == "plain_text", "按钮文本应为 plain_text"


# ===== build_verification_card（doc/09 §S4A 场景1，form + feedback input）=====


def test_build_verification_card_structure():
    """build_verification_card: schema 2.0 验收卡，form 含 btn_pass/btn_reject + feedback input。"""
    card = build_verification_card("task_1", "写测试用例", ["test_a.py", "test_b.py"])
    _assert_schema2(card)

    form = _find_form(card)
    assert form is not None, "验收卡应含 form"
    assert form["name"] == "verify_form", "form name 应为 verify_form"

    form_elements = form["elements"]
    # btn_pass（form_submit，验收通过）
    btn_pass = next(el for el in form_elements if el.get("name") == "btn_pass")
    _assert_form_submit_button(btn_pass, "btn_pass")
    assert btn_pass["type"] == "primary", "btn_pass 应为 primary"

    # btn_reject（form_submit，需要修改）
    btn_reject = next(el for el in form_elements if el.get("name") == "btn_reject")
    _assert_form_submit_button(btn_reject, "btn_reject")
    assert btn_reject["type"] == "danger", "btn_reject 应为 danger"

    # feedback input（issue #20 builder 侧补回）
    feedback_input = next(el for el in form_elements if el.get("tag") == "input")
    assert feedback_input["name"] == "feedback", "input name 应为 feedback"
    assert feedback_input["placeholder"]["tag"] == "plain_text", "input placeholder 应为 plain_text"


def test_build_verification_card_no_files():
    """build_verification_card: 无产出文件时显示「（无产出文件）」。"""
    card = build_verification_card("task_1", "空任务", [])
    _assert_schema2(card)
    md = card["body"]["elements"][0]
    assert md["tag"] == "markdown"
    assert "（无产出文件）" in md["content"]


def test_build_verification_card_no_behaviors_on_submit():
    """doc/09 V1: form_submit 按钮不能带 behaviors。"""
    card = build_verification_card("task_1", "任务", ["f.py"])
    form = _find_form(card)
    assert form is not None
    for el in form["elements"]:
        if el.get("tag") == "button" and el.get("action_type") == "form_submit":
            assert "behaviors" not in el, f"form_submit 按钮 {el.get('name')} 不能带 behaviors"


# ===== build_daily_summary_card（doc/09 §S5 状态1，form + checker 任务状态）=====


def test_build_daily_summary_card_structure():
    """build_daily_summary_card: schema 2.0 日终总结卡，checker 任务状态 + 确认按钮。"""
    card = build_daily_summary_card(
        daily_id="daily_1",
        date_str="2026-07-10",
        completed_tasks=[{"task_id": "t1", "name": "任务A"}],
        incomplete_tasks=[{"task_id": "t2", "name": "任务B"}],
        phase_health=[
            {"name": "阶段1", "completed": 1, "total": 2, "status": "进行中", "rate": 0.5},
        ],
    )
    _assert_schema2(card)

    form = _find_form(card)
    assert form is not None, "日终总结卡应含 form"
    assert form["name"] == "daily_summary_form"

    form_elements = form["elements"]
    # checker: 已完成任务 checked=true
    checker_t1 = next(el for el in form_elements if el.get("name") == "task_t1")
    assert checker_t1["tag"] == "checker"
    assert checker_t1["checked"] is True, "已完成任务应 checked=true"

    # checker: 未完成任务 checked=false
    checker_t2 = next(el for el in form_elements if el.get("name") == "task_t2")
    assert checker_t2["tag"] == "checker"
    assert checker_t2["checked"] is False, "未完成任务应 checked=false"

    # 确认按钮（form_submit）
    confirm_btn = next(el for el in form_elements if el.get("name") == "confirm_btn")
    _assert_form_submit_button(confirm_btn, "confirm_btn")


def test_build_daily_summary_card_empty_tasks():
    """build_daily_summary_card: 无任务时仍应有确认按钮。"""
    card = build_daily_summary_card(
        daily_id="daily_1",
        date_str="2026-07-10",
        completed_tasks=[],
        incomplete_tasks=[],
        phase_health=[],
    )
    _assert_schema2(card)
    form = _find_form(card)
    assert form is not None
    confirm_btn = next(el for el in form["elements"] if el.get("name") == "confirm_btn")
    _assert_form_submit_button(confirm_btn, "confirm_btn")


# ===== build_phase_linking_card（doc/09 §S8，form + date_picker + column_set）=====


def test_build_phase_linking_card_structure():
    """build_phase_linking_card: schema 2.0 阶段衔接卡，date_picker + column_set 并列按钮。"""
    card = build_phase_linking_card(
        completed_phase_name="阶段1",
        next_phase_id="phase_2",
        next_phase_name="阶段2",
        suggested_deadline="2026-08-01",
    )
    _assert_schema2(card)

    form = _find_form(card)
    assert form is not None, "阶段衔接卡应含 form"
    assert form["name"] == "phase_linking_form"

    form_elements = form["elements"]
    # date_picker（name=deadline，required，initial_date）
    date_picker = next(el for el in form_elements if el.get("tag") == "date_picker")
    assert date_picker["name"] == "deadline", "date_picker name 应为 deadline"
    assert date_picker["required"] is True, "date_picker 应 required=true"
    assert date_picker["initial_date"] == "2026-08-01", "initial_date 应为建议 deadline"

    # column_set 内两个 form_submit 按钮
    col_set = next(el for el in form_elements if el.get("tag") == "column_set")
    assert len(col_set["columns"]) == 2, "应有两个并列列"

    btn_activate = col_set["columns"][0]["elements"][0]
    _assert_form_submit_button(btn_activate, "btn_activate")
    assert btn_activate["type"] == "primary", "btn_activate 应为 primary"

    btn_defer = col_set["columns"][1]["elements"][0]
    _assert_form_submit_button(btn_defer, "btn_defer")
    assert btn_defer["type"] == "default", "btn_defer 应为 default"


# ===== build_theme_completed_card（doc/09 §S8其他子卡，form 外 behaviors callback）=====


def test_build_theme_completed_card_structure():
    """build_theme_completed_card: schema 2.0 专题完成卡，每专题一个回调按钮。"""
    card = build_theme_completed_card(
        completed_theme_name="专题A",
        other_themes=[
            {"theme_id": "th1", "name": "专题B", "type": "learning"},
            {"theme_id": "th2", "name": "专题C", "type": "dev"},
        ],
    )
    _assert_schema2(card)

    buttons = _find_buttons(card)
    assert len(buttons) == 2, "应有 2 个激活按钮"
    for btn in buttons:
        _assert_callback_button(btn)
        assert btn["behaviors"][0]["value"]["action_id"] == "story8_去激活"


def test_build_theme_completed_card_no_other_themes():
    """build_theme_completed_card: 无其他专题时无按钮。"""
    card = build_theme_completed_card(
        completed_theme_name="专题A",
        other_themes=[],
    )
    _assert_schema2(card)
    buttons = _find_buttons(card)
    assert len(buttons) == 0, "无其他专题时不应有按钮"


# ===== build_goal_completed_card（doc/09 §S8其他子卡，纯通知无按钮）=====


def test_build_goal_completed_card_structure():
    """build_goal_completed_card: schema 2.0 目标完成卡，无按钮。"""
    card = build_goal_completed_card("读完一本书")
    _assert_schema2(card)
    buttons = _find_buttons(card)
    assert len(buttons) == 0, "目标完成卡不应有按钮"
    assert card["header"]["template"] == "green", "目标完成卡 header 应为 green"


# ===== build_start_date_reminder_card（doc/09 §S8其他子卡，form 外 callback）=====


def test_build_start_date_reminder_card_structure():
    """build_start_date_reminder_card: schema 2.0 开始日提醒卡，1 个回调按钮。"""
    card = build_start_date_reminder_card(
        goal_id="goal_1",
        goal_name="学英语",
        scheduled_start_date="2026-07-10",
    )
    _assert_schema2(card)
    buttons = _find_buttons(card)
    assert len(buttons) == 1, "应有 1 个去激活按钮"
    _assert_callback_button(buttons[0])
    assert buttons[0]["behaviors"][0]["value"]["action_id"] == "story8_去激活"
    assert buttons[0]["behaviors"][0]["value"]["goal_id"] == "goal_1"


# ===== build_deadline_reminder_card（doc/09 §S8其他子卡，form 外 callback）=====


def test_build_deadline_reminder_card_structure():
    """build_deadline_reminder_card: schema 2.0 deadline 提醒卡，1 个回调按钮。"""
    card = build_deadline_reminder_card(
        phase_id="phase_1",
        phase_name="阶段1",
        deadline="2026-07-15",
    )
    _assert_schema2(card)
    buttons = _find_buttons(card)
    assert len(buttons) == 1, "应有 1 个去页面调整按钮"
    _assert_callback_button(buttons[0])
    assert buttons[0]["behaviors"][0]["value"]["action_id"] == "story8_去页面调整"
    assert buttons[0]["behaviors"][0]["value"]["phase_id"] == "phase_1"


# ===== build_plan_reminder_card（doc/01 S8 AC：未确认计划 10:00 提醒，纯提醒无按钮）=====


def test_build_plan_reminder_card_structure():
    """build_plan_reminder_card: schema 2.0 计划未确认提醒，无按钮。"""
    card = build_plan_reminder_card("2026-07-10")
    _assert_schema2(card)
    buttons = _find_buttons(card)
    assert len(buttons) == 0, "计划提醒卡不应有按钮"


# ===== build_summary_reminder_card（doc/01 S8 AC：未做日终总结 21:00 提醒，纯提醒无按钮）=====


def test_build_summary_reminder_card_structure():
    """build_summary_reminder_card: schema 2.0 日终未做提醒，无按钮。"""
    card = build_summary_reminder_card("2026-07-10")
    _assert_schema2(card)
    buttons = _find_buttons(card)
    assert len(buttons) == 0, "日终提醒卡不应有按钮"


# ===========================================================================
# PR-B 新增 builder 测试（6 个，doc/09 实证规格）
# ===========================================================================


# ===== build_plan_overview_card（doc/09 §S1 确认前，无 form + callback 按钮）=====


def test_build_plan_overview_card_structure():
    """build_plan_overview_card: schema 2.0 方案总览卡，markdown + 确认方案 callback 按钮。"""
    card = build_plan_overview_card(
        goal_name="知识库构建",
        theme_count=4,
        phase_count=12,
        task_count=36,
        draft_id="draft_abc",
    )
    _assert_schema2(card)

    # 无 form（纯 markdown + 按钮）
    form = _find_form(card)
    assert form is None, "方案总览卡不应有 form"

    # 确认方案按钮（form 外 callback）
    buttons = _find_buttons(card)
    assert len(buttons) == 1, "应有 1 个确认方案按钮"
    _assert_callback_button(buttons[0])
    value = buttons[0]["behaviors"][0]["value"]
    assert value["action_id"] == "story1_确认方案"
    assert value["draft_id"] == "draft_abc"

    # markdown 含目标名 + 统计数字
    md = card["body"]["elements"][0]
    assert "知识库构建" in md["content"]
    assert "4" in md["content"]  # theme_count
    assert "12" in md["content"]  # phase_count
    assert "36" in md["content"]  # task_count


def test_build_plan_overview_card_header_blue():
    """build_plan_overview_card: header 应为 blue（待操作）。"""
    card = build_plan_overview_card("目标", 1, 1, 1, "d1")
    assert card["header"]["template"] == "blue", "确认前 header 应为 blue"


# ===== build_schedule_card_a（doc/09 §S2 状态1，form + checker 专题 + next_btn）=====


def test_build_schedule_card_a_structure():
    """build_schedule_card_a: schema 2.0 调度卡 A，form 含每专题 checker + next_btn form_submit。"""
    card = build_schedule_card_a(
        goal_name="知识库构建",
        themes=[
            {"theme_id": "t1", "name": "知识获取", "type": "learning"},
            {"theme_id": "t2", "name": "知识沉淀", "type": "learning"},
        ],
    )
    _assert_schema2(card)

    form = _find_form(card)
    assert form is not None, "调度卡 A 应含 form"
    assert form["name"] == "schedule_form_a"

    form_elements = form["elements"]
    # 每专题一个 checker
    checkers = [el for el in form_elements if el.get("tag") == "checker"]
    assert len(checkers) == 2, "应有 2 个专题 checker"

    # checker name = theme_{id}
    assert checkers[0]["name"] == "theme_t1"
    assert checkers[1]["name"] == "theme_t2"

    # checker text 含专题名 + 类型
    assert "知识获取" in checkers[0]["text"]["content"]
    assert "learning" in checkers[0]["text"]["content"]

    # next_btn（form_submit，不带 behaviors）
    next_btn = next(el for el in form_elements if el.get("name") == "next_btn")
    _assert_form_submit_button(next_btn, "next_btn")
    assert next_btn["type"] == "primary"


def test_build_schedule_card_a_h5_url():
    """build_schedule_card_a: 传 h5_url 时 markdown 含链接。"""
    card = build_schedule_card_a(
        goal_name="目标",
        themes=[{"theme_id": "t1", "name": "专题", "type": "dev"}],
        h5_url="https://h5.example.com/config",
    )
    elements = card["body"]["elements"]
    md_link = next(
        el for el in elements if el.get("tag") == "markdown" and "配置页" in el.get("content", "")
    )
    assert "https://h5.example.com/config" in md_link["content"], "应含 h5_url 链接"


def test_build_schedule_card_a_no_h5_url():
    """build_schedule_card_a: 不传 h5_url 时纯文字提示（无链接）。"""
    card = build_schedule_card_a(
        goal_name="目标",
        themes=[],
    )
    elements = card["body"]["elements"]
    md_link = next(
        el for el in elements if el.get("tag") == "markdown" and "配置页" in el.get("content", "")
    )
    assert "(" not in md_link["content"].split("配置页")[1], "不传 h5_url 时不应有 markdown 链接"


# ===== build_schedule_card_b（doc/09 §S2 状态2，form + date_picker + confirm_btn）=====


def test_build_schedule_card_b_structure():
    """build_schedule_card_b: date_picker per phase + confirm_btn form_submit。"""
    card = build_schedule_card_b(
        goal_name="知识库构建",
        phases=[
            {
                "theme_id": "t1",
                "theme_name": "知识获取",
                "phase_name": "阶段1：知识获取",
                "type": "learning",
            },
            {
                "theme_id": "t2",
                "theme_name": "知识沉淀",
                "phase_name": "阶段1：知识沉淀",
                "type": "learning",
            },
        ],
    )
    _assert_schema2(card)

    form = _find_form(card)
    assert form is not None, "调度卡 B 应含 form"
    assert form["name"] == "schedule_form_b"

    form_elements = form["elements"]
    # 每阶段一个 div + 一个 date_picker
    date_pickers = [el for el in form_elements if el.get("tag") == "date_picker"]
    assert len(date_pickers) == 2, "应有 2 个 date_picker"

    # date_picker name = dl_theme_{id}（doc/09 §S2 状态2）
    assert date_pickers[0]["name"] == "dl_theme_t1"
    assert date_pickers[1]["name"] == "dl_theme_t2"

    # date_picker required=true
    for dp in date_pickers:
        assert dp["required"] is True, "date_picker 应 required=true"
        assert dp["placeholder"]["tag"] == "plain_text"

    # div 含阶段名（lark_md）
    divs = [el for el in form_elements if el.get("tag") == "div"]
    assert len(divs) == 2, "应有 2 个 div"
    assert divs[0]["text"]["tag"] == "lark_md"
    assert "知识获取" in divs[0]["text"]["content"]
    assert "阶段1：知识获取" in divs[0]["text"]["content"]

    # confirm_btn（form_submit）
    confirm_btn = next(el for el in form_elements if el.get("name") == "confirm_btn")
    _assert_form_submit_button(confirm_btn, "confirm_btn")
    assert confirm_btn["type"] == "primary"


def test_build_schedule_card_b_no_behaviors_on_submit():
    """doc/09 V1: form_submit 按钮不能带 behaviors。"""
    card = build_schedule_card_b("目标", [])
    form = _find_form(card)
    assert form is not None
    for el in form["elements"]:
        if el.get("tag") == "button" and el.get("action_type") == "form_submit":
            assert "behaviors" not in el, f"form_submit 按钮 {el.get('name')} 不能带 behaviors"


# ===== build_daily_plan_card（doc/09 §S3 状态1，form + checker 候选任务 + 前置）=====


def test_build_daily_plan_card_structure():
    """build_daily_plan_card: schema 2.0 今日计划卡，checker 候选任务 + 前置 + confirm_btn。"""
    card = build_daily_plan_card(
        date_str="2026-07-10",
        candidate_tasks=[
            {
                "task_id": "t1",
                "name": "信息获取渠道设计",
                "executor": "human",
                "phase_info": "知识获取/阶段1",
            },
            {
                "task_id": "t2",
                "name": "部署 RSSHub",
                "executor": "agent",
                "phase_info": "知识获取/阶段1",
            },
        ],
        prerequisites=[
            {"subtask_id": "p1", "name": "准备 RSSHub 环境"},
            {"subtask_id": "p2", "name": "阅读 SimHash 原理"},
        ],
    )
    _assert_schema2(card)

    form = _find_form(card)
    assert form is not None, "今日计划卡应含 form"
    assert form["name"] == "daily_plan_form"

    form_elements = form["elements"]

    # 候选任务 checker
    checker_t1 = next(el for el in form_elements if el.get("name") == "task_t1")
    assert checker_t1["tag"] == "checker"
    assert "信息获取渠道设计" in checker_t1["text"]["content"]
    assert "[人]" in checker_t1["text"]["content"], "human executor 应显示 [人]"
    assert "知识获取/阶段1" in checker_t1["text"]["content"], "应含 phase_info"

    checker_t2 = next(el for el in form_elements if el.get("name") == "task_t2")
    assert checker_t2["tag"] == "checker"
    assert "[智能体]" in checker_t2["text"]["content"], "agent executor 应显示 [智能体]"

    # 前置 checker（独立组）
    checker_p1 = next(el for el in form_elements if el.get("name") == "pre_p1")
    assert checker_p1["tag"] == "checker"
    assert "准备 RSSHub 环境" in checker_p1["text"]["content"]

    checker_p2 = next(el for el in form_elements if el.get("name") == "pre_p2")
    assert checker_p2["tag"] == "checker"

    # confirm_btn（form_submit）
    confirm_btn = next(el for el in form_elements if el.get("name") == "confirm_btn")
    _assert_form_submit_button(confirm_btn, "confirm_btn")


def test_build_daily_plan_card_no_prerequisites():
    """build_daily_plan_card: 无前置时不渲染前置区块。"""
    card = build_daily_plan_card(
        date_str="2026-07-10",
        candidate_tasks=[{"task_id": "t1", "name": "任务", "executor": "human"}],
        prerequisites=[],
    )
    form = _find_form(card)
    assert form is not None
    form_elements = form["elements"]
    # 无前置 checker
    pre_checkers = [el for el in form_elements if el.get("name", "").startswith("pre_")]
    assert len(pre_checkers) == 0, "无前置时不应有 pre_ checker"
    # 仍含确认按钮
    confirm_btn = next(el for el in form_elements if el.get("name") == "confirm_btn")
    _assert_form_submit_button(confirm_btn, "confirm_btn")


def test_build_daily_plan_card_empty_tasks():
    """build_daily_plan_card: 无候选任务时仍含确认按钮。"""
    card = build_daily_plan_card(
        date_str="2026-07-10",
        candidate_tasks=[],
        prerequisites=[],
    )
    _assert_schema2(card)
    form = _find_form(card)
    assert form is not None
    confirm_btn = next(el for el in form["elements"] if el.get("name") == "confirm_btn")
    _assert_form_submit_button(confirm_btn, "confirm_btn")


# ===== build_task_complete_card（doc/09 §S4A 场景4，已完成展示 + 待确认 checker）=====


def test_build_task_complete_card_structure():
    """build_task_complete_card: 已完成 div + 待确认 checker + confirm_btn。"""
    card = build_task_complete_card(
        workspace_name="ws_test",
        completed_tasks=[
            {"name": "任务A", "executor": "human"},
            {"name": "任务B", "executor": "agent"},
        ],
        pending_tasks=[
            {"id": "t1", "name": "任务C", "executor": "human", "is_agent": False},
            {"id": "t2", "name": "任务D", "executor": "agent", "is_agent": True},
        ],
    )
    _assert_schema2(card)

    elements = card["body"]["elements"]
    # 已完成任务（div lark_md，不可操作）
    divs = [el for el in elements if el.get("tag") == "div"]
    assert len(divs) == 2, "应有 2 个已完成任务 div"
    assert divs[0]["text"]["tag"] == "lark_md"
    assert "任务A" in divs[0]["text"]["content"]
    assert "[人]" in divs[0]["text"]["content"]
    assert "任务B" in divs[1]["text"]["content"]
    assert "[智能体]" in divs[1]["text"]["content"]

    form = _find_form(card)
    assert form is not None, "确认完成卡应含 form"
    assert form["name"] == "confirm_complete_form"

    form_elements = form["elements"]
    # 待确认任务 checker（name=task_{id}）
    checker_t1 = next(el for el in form_elements if el.get("name") == "task_t1")
    assert checker_t1["tag"] == "checker"
    assert "任务C" in checker_t1["text"]["content"]
    assert "[人]" in checker_t1["text"]["content"]

    checker_t2 = next(el for el in form_elements if el.get("name") == "task_t2")
    assert checker_t2["tag"] == "checker"
    assert "[智能体]" in checker_t2["text"]["content"]

    # confirm_btn（form_submit）
    confirm_btn = next(el for el in form_elements if el.get("name") == "confirm_btn")
    _assert_form_submit_button(confirm_btn, "confirm_btn")


def test_build_task_complete_card_no_completed():
    """build_task_complete_card: 无已完成任务时显示「（无）」。"""
    card = build_task_complete_card(
        workspace_name="ws",
        completed_tasks=[],
        pending_tasks=[],
    )
    _assert_schema2(card)
    elements = card["body"]["elements"]
    # 应有 div 显示「（无）」
    no_task_div = next(
        el
        for el in elements
        if el.get("tag") == "div" and "（无）" in el.get("text", {}).get("content", "")
    )
    assert no_task_div is not None, "无已完成任务时应显示「（无）」"
    # 仍含 form + confirm 按钮
    form = _find_form(card)
    assert form is not None
    confirm_btn = next(el for el in form["elements"] if el.get("name") == "confirm_btn")
    _assert_form_submit_button(confirm_btn, "confirm_btn")


# ===== build_weekly_summary_card（doc/09 §S6 状态1，纯展示 + 已阅 callback）=====


def test_build_weekly_summary_card_structure():
    """build_weekly_summary_card: 含任务列表/趋势/健康度/建议 + 已阅 callback。"""
    card = build_weekly_summary_card(
        week="2026-W28",
        start_date="2026-07-06",
        end_date="2026-07-12",
        completed_tasks=[
            {"date": "07-06", "task_name": "信息获取渠道设计", "executor": "human"},
            {"date": "07-08", "task_name": "部署 RSSHub", "executor": "agent"},
        ],
        daily_trends=[
            {"date": "07-06", "weekday": "周一", "completed": 1, "total": 2},
            {"date": "07-07", "weekday": "周二", "completed": 0, "total": 1},
        ],
        phase_health=[
            {"name": "阶段1", "completed": 3, "total": 5, "status": "进行中"},
        ],
        agent_output_count=7,
        next_week_advice="加快阶段1进度，优先完成剩余2个任务",
    )
    _assert_schema2(card)

    # 无 form（纯展示 + 已阅按钮）
    form = _find_form(card)
    assert form is None, "周总结卡不应有 form"

    elements = card["body"]["elements"]
    # 验证各 section 的 markdown 内容
    all_md = [el for el in elements if el.get("tag") == "markdown"]
    all_content = "\n".join(el["content"] for el in all_md)

    # 日期范围
    assert "2026-07-06" in all_content and "2026-07-12" in all_content
    # 本周完成任务列表（含日期 + 任务名 + 执行主体）
    assert "07-06" in all_content and "信息获取渠道设计" in all_content
    assert "[人]" in all_content
    assert "07-08" in all_content and "部署 RSSHub" in all_content
    assert "[智能体]" in all_content
    # 每日完成趋势
    assert "周一" in all_content and "1/2" in all_content
    # 阶段健康度
    assert "阶段1" in all_content and "3/5" in all_content and "进行中" in all_content
    # 智能体产出
    assert "7" in all_content and "个文件" in all_content
    # 下周建议
    assert "加快阶段1进度" in all_content

    # 已阅按钮（form 外 callback）
    buttons = _find_buttons(card)
    assert len(buttons) == 1, "应有 1 个已阅按钮"
    _assert_callback_button(buttons[0])
    value = buttons[0]["behaviors"][0]["value"]
    assert value["action_id"] == "story6_已阅周总结"
    assert value["week"] == "2026-W28"


def test_build_weekly_summary_card_empty_tasks():
    """build_weekly_summary_card: 无完成任务时显示「（本周无完成任务）」。"""
    card = build_weekly_summary_card(
        week="2026-W28",
        start_date="2026-07-06",
        end_date="2026-07-12",
        completed_tasks=[],
        daily_trends=[],
        phase_health=[],
        agent_output_count=0,
        next_week_advice="无建议",
    )
    _assert_schema2(card)
    all_md = [el for el in card["body"]["elements"] if el.get("tag") == "markdown"]
    all_content = "\n".join(el["content"] for el in all_md)
    assert "（本周无完成任务）" in all_content, "无完成任务时应显示提示"
    # 仍含已阅按钮
    buttons = _find_buttons(card)
    assert len(buttons) == 1, "即使无数据也应有已阅按钮"


def test_weekly_summary_card_no_subtask_stats():
    """doc/09 §S6 实现注意：周总结不含子任务统计。"""
    card = build_weekly_summary_card(
        week="2026-W28",
        start_date="2026-07-06",
        end_date="2026-07-12",
        completed_tasks=[],
        daily_trends=[],
        phase_health=[],
        agent_output_count=0,
        next_week_advice="无",
    )
    all_md = [el for el in card["body"]["elements"] if el.get("tag") == "markdown"]
    all_content = "\n".join(el["content"] for el in all_md)
    assert "子任务" not in all_content, "周总结不应含子任务统计"
