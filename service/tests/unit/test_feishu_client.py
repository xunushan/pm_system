"""Story8/通用 单元测试：FeishuClient（mock httpx，不真连飞书）。

重点覆盖 issue #14：app_id 为空时所有推送方法 graceful skip（不调 httpx），
避免请求 token API 触发 KeyError: 'tenant_access_token'。
"""

from unittest.mock import MagicMock, patch

from app.clients.feishu import FeishuClient


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
