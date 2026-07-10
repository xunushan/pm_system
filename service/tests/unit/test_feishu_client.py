"""Story8/通用 单元测试：FeishuClient（mock httpx，不真连飞书）。

重点覆盖 issue #14：app_id 为空时所有推送方法 graceful skip（不调 httpx），
避免请求 token API 触发 KeyError: 'tenant_access_token'。

另含 9 个 build_*_card 结构校验测试（端到端验证发现旧格式导致飞书 230099）。
"""

from unittest.mock import MagicMock, patch

from app.clients.feishu import (
    FeishuClient,
    build_daily_summary_card,
    build_deadline_reminder_card,
    build_goal_completed_card,
    build_phase_linking_card,
    build_plan_reminder_card,
    build_start_date_reminder_card,
    build_summary_reminder_card,
    build_theme_completed_card,
    build_verification_card,
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
# 卡片结构校验测试（端到端验证发现旧格式导致飞书 230099）
#
# 旧格式（错误）：顶层 "type":"template" + "data" 包裹 column_set
#   -> 飞书返回 code 230099 "content's type illegal"
# 新格式（正确）：顶层 config + elements，元素用 tag 而非 type
#   -> 飞书实测推送成功 HTTP 200 code 0
#
# 以下测试直接断言 builder 返回的 dict 结构，不 mock httpx。
# ---------------------------------------------------------------------------


def _assert_card_structure(card: dict, expect_buttons: bool = True):
    """通用断言：飞书官方卡片结构。

    - 顶层有 ``config`` + ``elements``，无 ``"type": "template"`` / ``data``
    - elements[0] 是 markdown（tag="markdown"）
    - 若 expect_buttons=True：按钮在 tag="action" 的 block 内，每个按钮 tag="button"
    - 若 expect_buttons=False：elements 只有 markdown，无 action block
    """
    assert "config" in card, "卡片缺 config 键"
    assert "elements" in card, "卡片缺 elements 键"
    assert card.get("type") != "template", "卡片仍用旧 template 结构"
    assert "data" not in card, "卡片仍用旧 data 包裹"

    elements = card["elements"]
    assert len(elements) >= 1, "elements 不能为空"
    assert elements[0]["tag"] == "markdown", "第一个元素应为 markdown"
    assert "content" in elements[0], "markdown 元素缺 content"

    if expect_buttons:
        action_blocks = [e for e in elements if e.get("tag") == "action"]
        assert len(action_blocks) >= 1, "有按钮的卡片应含 action block"
        for btn in action_blocks[0]["actions"]:
            assert btn["tag"] == "button", "按钮应使用 tag 而非 type"
            assert btn["text"]["tag"] == "plain_text", "按钮文本应使用 tag"
            assert "value" in btn, "按钮缺 value（回调数据）"
            assert "action_id" in btn["value"], "按钮 value 缺 action_id"
    else:
        action_blocks = [e for e in elements if e.get("tag") == "action"]
        assert len(action_blocks) == 0, "无按钮卡片不应有 action block"


def test_build_verification_card_structure():
    """build_verification_card: 验收卡，2 个按钮（验收通过/需要修改）。"""
    card = build_verification_card("task_1", "写测试用例", ["test_a.py", "test_b.py"])
    _assert_card_structure(card, expect_buttons=True)
    actions = [e for e in card["elements"] if e.get("tag") == "action"][0]["actions"]
    assert len(actions) == 2, "验收卡应有 2 个按钮"


def test_build_verification_card_no_files():
    """build_verification_card: 无产出文件时的边界。"""
    card = build_verification_card("task_1", "空任务", [])
    _assert_card_structure(card, expect_buttons=True)
    # 无文件时应显示「（无产出文件）」
    md = card["elements"][0]["content"]
    assert "（无产出文件）" in md


def test_build_daily_summary_card_structure():
    """build_daily_summary_card: 日终总结卡，动态按钮（已完成+未完成+确认）。"""
    card = build_daily_summary_card(
        daily_id="daily_1",
        date_str="2026-07-10",
        completed_tasks=[{"task_id": "t1", "name": "任务A"}],
        incomplete_tasks=[{"task_id": "t2", "name": "任务B"}],
        phase_health=[
            {"name": "阶段1", "completed": 1, "total": 2, "status": "进行中", "rate": 0.5},
        ],
    )
    _assert_card_structure(card, expect_buttons=True)
    actions = [e for e in card["elements"] if e.get("tag") == "action"][0]["actions"]
    # 1 个标记未完成 + 1 个标记完成 + 1 个确认 = 3 个按钮
    assert len(actions) == 3


def test_build_daily_summary_card_empty_tasks():
    """build_daily_summary_card: 无任务时的边界（只有确认按钮）。"""
    card = build_daily_summary_card(
        daily_id="daily_1",
        date_str="2026-07-10",
        completed_tasks=[],
        incomplete_tasks=[],
        phase_health=[],
    )
    _assert_card_structure(card, expect_buttons=True)
    actions = [e for e in card["elements"] if e.get("tag") == "action"][0]["actions"]
    assert len(actions) == 1, "无任务时仍应有确认日终总结按钮"


def test_build_phase_linking_card_structure():
    """build_phase_linking_card: 阶段衔接卡，2 个按钮（确认激活/暂不激活）。"""
    card = build_phase_linking_card(
        completed_phase_name="阶段1",
        next_phase_id="phase_2",
        next_phase_name="阶段2",
        suggested_deadline="2026-08-01",
    )
    _assert_card_structure(card, expect_buttons=True)
    actions = [e for e in card["elements"] if e.get("tag") == "action"][0]["actions"]
    assert len(actions) == 2


def test_build_theme_completed_card_structure():
    """build_theme_completed_card: 专题完成卡，动态按钮。"""
    card = build_theme_completed_card(
        completed_theme_name="专题A",
        other_themes=[
            {"theme_id": "th1", "name": "专题B", "type": "learning"},
            {"theme_id": "th2", "name": "专题C", "type": "dev"},
        ],
    )
    _assert_card_structure(card, expect_buttons=True)
    actions = [e for e in card["elements"] if e.get("tag") == "action"][0]["actions"]
    assert len(actions) == 2


def test_build_theme_completed_card_no_other_themes():
    """build_theme_completed_card: 无其他专题时的边界（无按钮）。"""
    card = build_theme_completed_card(
        completed_theme_name="专题A",
        other_themes=[],
    )
    _assert_card_structure(card, expect_buttons=False)


def test_build_goal_completed_card_structure():
    """build_goal_completed_card: 目标完成卡，无按钮。"""
    card = build_goal_completed_card("读完一本书")
    _assert_card_structure(card, expect_buttons=False)


def test_build_start_date_reminder_card_structure():
    """build_start_date_reminder_card: 开始日提醒卡，1 个按钮。"""
    card = build_start_date_reminder_card(
        goal_id="goal_1",
        goal_name="学英语",
        scheduled_start_date="2026-07-10",
    )
    _assert_card_structure(card, expect_buttons=True)
    actions = [e for e in card["elements"] if e.get("tag") == "action"][0]["actions"]
    assert len(actions) == 1


def test_build_deadline_reminder_card_structure():
    """build_deadline_reminder_card: deadline 提醒卡，1 个按钮。"""
    card = build_deadline_reminder_card(
        phase_id="phase_1",
        phase_name="阶段1",
        deadline="2026-07-15",
    )
    _assert_card_structure(card, expect_buttons=True)
    actions = [e for e in card["elements"] if e.get("tag") == "action"][0]["actions"]
    assert len(actions) == 1


def test_build_plan_reminder_card_structure():
    """build_plan_reminder_card: 计划未确认提醒，无按钮。"""
    card = build_plan_reminder_card("2026-07-10")
    _assert_card_structure(card, expect_buttons=False)


def test_build_summary_reminder_card_structure():
    """build_summary_reminder_card: 日终未做提醒，无按钮。"""
    card = build_summary_reminder_card("2026-07-10")
    _assert_card_structure(card, expect_buttons=False)
