"""Story8 单元测试：事件 handler（handlers.py）。

测试：
  - on_phase_completed: 查下一阶段 + 推衔接卡片 + Redis 记推送时间
  - on_phase_completed: 无下一阶段 -> no-op
  - on_theme_completed: 列未完成专题 + 推卡片
  - on_theme_completed: 无其他未完成专题 -> no-op
  - on_goal_completed: 推目标完成通知
"""

from datetime import date

from app.supervisor.event_bus import LINKING_PUSHED_KEY
from app.supervisor.handlers import on_goal_completed, on_phase_completed, on_theme_completed
from tests._factory import make_tree


class FakeFeishu:
    """模拟飞书客户端，记录 send_card 调用。"""

    def __init__(self):
        self.cards = []

    def send_card(self, chat_id, card):
        self.cards.append({"chat_id": chat_id, "card": card})


def _extract_action_ids(card):
    """从卡片提取所有 action_id（schema 2.0：body.elements 里的 button behaviors callback）。"""
    action_ids = []
    elements = card.get("body", {}).get("elements", card.get("elements", []))
    for el in elements:
        if el.get("tag") == "button" and "behaviors" in el:
            for behavior in el["behaviors"]:
                if behavior.get("type") == "callback":
                    action_ids.append(behavior.get("value", {}).get("action_id"))
    return action_ids


def _extract_form_submit_names(card):
    """从卡片提取所有 form_submit 按钮的 name（schema 2.0 form 内提交按钮）。

    递归搜索 form.elements 内的 button（含 column_set 嵌套，doc/09 §S8）。
    """
    names = []
    elements = card.get("body", {}).get("elements", card.get("elements", []))
    for el in elements:
        if el.get("tag") == "form":
            _collect_submit_names(el.get("elements", []), names)
    return names


def _collect_submit_names(elements: list, names: list):
    """递归收集 form_submit 按钮的 name（处理 column_set 嵌套）。"""
    for el in elements:
        if el.get("tag") == "button" and el.get("action_type") == "form_submit":
            names.append(el.get("name"))
        elif el.get("tag") == "column_set":
            for col in el.get("columns", []):
                _collect_submit_names(col.get("elements", []), names)


def test_on_phase_completed_pushes_linking_card(db_session, fake_redis):
    """阶段完成 -> 推衔接卡片（含 确认激活/暂不激活 + deadline）。"""
    goal, themes, phases = make_tree(db_session, n_themes=1, phases_per_theme=2)
    goal.time_range_end = date(2026, 8, 1)
    db_session.flush()
    feishu = FakeFeishu()

    on_phase_completed(phases[0].id, db=db_session, feishu=feishu, redis_client=fake_redis)

    assert len(feishu.cards) == 1
    card = feishu.cards[0]["card"]
    # schema 2.0: form_submit 按钮靠 name 区分（doc/09 §S8）
    submit_names = _extract_form_submit_names(card)
    assert "btn_activate" in submit_names
    assert "btn_defer" in submit_names


def test_on_phase_completed_records_redis(db_session, fake_redis):
    """阶段完成 -> Redis 记衔接推送时间。"""
    goal, themes, phases = make_tree(db_session, n_themes=1, phases_per_theme=2)
    db_session.flush()

    on_phase_completed(phases[0].id, db=db_session, feishu=FakeFeishu(), redis_client=fake_redis)

    key = LINKING_PUSHED_KEY.format(phase_id=phases[0].id)
    assert fake_redis.exists(key)
    val = fake_redis.get(key)
    assert val is not None  # ISO 时间字符串


def test_on_phase_completed_no_next_phase_noop(db_session, fake_redis):
    """无下一阶段（最后一个）-> 不推卡片。"""
    goal, themes, phases = make_tree(db_session, n_themes=1, phases_per_theme=1)
    db_session.flush()
    feishu = FakeFeishu()

    on_phase_completed(phases[0].id, db=db_session, feishu=feishu, redis_client=fake_redis)

    assert len(feishu.cards) == 0
    key = LINKING_PUSHED_KEY.format(phase_id=phases[0].id)
    assert not fake_redis.exists(key)


def test_on_phase_completed_phase_not_exists(db_session, fake_redis):
    """phase 不存在 -> 不崩溃。"""
    on_phase_completed("nonexistent", db=db_session, feishu=FakeFeishu(), redis_client=fake_redis)


def test_on_theme_completed_pushes_other_themes(db_session):
    """专题完成 -> 推卡片列出同 goal 未完成的其他专题。"""
    goal, themes, phases = make_tree(db_session, n_themes=3, phases_per_theme=1)
    themes[0].status = "已完成"
    db_session.flush()
    feishu = FakeFeishu()

    on_theme_completed(themes[0].id, db=db_session, feishu=feishu)

    assert len(feishu.cards) == 1
    card = feishu.cards[0]["card"]
    action_ids = _extract_action_ids(card)
    # 2 个其他未完成专题 -> 2 个"去激活"按钮
    assert len([a for a in action_ids if a == "story8_去激活"]) == 2


def test_on_theme_completed_no_other_themes_noop(db_session):
    """无其他未完成专题 -> 不推卡片。"""
    goal, themes, phases = make_tree(db_session, n_themes=1, phases_per_theme=1)
    themes[0].status = "已完成"
    db_session.flush()
    feishu = FakeFeishu()

    on_theme_completed(themes[0].id, db=db_session, feishu=feishu)

    assert len(feishu.cards) == 0


def test_on_theme_completed_excludes_completed(db_session):
    """已完成的专题不列入（只列未完成+未暂停的）。"""
    goal, themes, phases = make_tree(db_session, n_themes=3, phases_per_theme=1)
    themes[0].status = "已完成"
    themes[1].status = "已完成"  # 也完成了
    db_session.flush()
    feishu = FakeFeishu()

    on_theme_completed(themes[0].id, db=db_session, feishu=feishu)

    assert len(feishu.cards) == 1
    # 只有 themes[2] 未完成
    action_ids = _extract_action_ids(feishu.cards[0]["card"])
    assert len([a for a in action_ids if a == "story8_去激活"]) == 1


def test_on_goal_completed_pushes_notification(db_session):
    """目标完成 -> 推目标完成通知卡片（无按钮）。"""
    goal, themes, phases = make_tree(db_session)
    db_session.flush()
    feishu = FakeFeishu()

    on_goal_completed(goal.id, db=db_session, feishu=feishu)

    assert len(feishu.cards) == 1
    # 纯通知，无 action block（无按钮）
    action_ids = _extract_action_ids(feishu.cards[0]["card"])
    assert action_ids == []


def test_on_goal_completed_goal_not_exists(db_session):
    """goal 不存在 -> 不崩溃。"""
    on_goal_completed("nonexistent", db=db_session, feishu=FakeFeishu())
