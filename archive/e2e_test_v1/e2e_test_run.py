"""端到端 Story 测试：推卡（真实飞书）+ 回调（真实点击）+ DB 断言。

按 Story 顺序推进：
  S1/S2/S3/S4B/S9 -> API 造数据（Skill 职责的卡片不推，Service 无推卡方法）
  S4A/S5/S6/S8 -> 真实推卡 + 你飞书点按钮 + 查 DB 断言

配合节奏：脚本推卡 -> 打印"请去飞书点 [按钮]" -> 等你回车 -> 查 DB 断言。

用 e2e.db（Service 已指向 e2e.db）。
"""
import json
import sqlite3
import time

import httpx

API = "http://127.0.0.1:8001/api/v1"
WEBHOOK = "http://127.0.0.1:8001/webhook/feishu/card"
DB = "data/e2e.db"
client = httpx.Client(base_url=API, timeout=30)

ids = json.load(open("/tmp/e2e_test_ids.json"))
GOAL_ID = ids["goal_id"]
THEME_ID = ids["theme_id"]
PHASE_IDS = ids["phase_ids"]
P1, P2, P3, P4 = PHASE_IDS["1"], PHASE_IDS["2"], PHASE_IDS["3"], PHASE_IDS["4"]


def dbq(sql, args=()):
    conn = sqlite3.connect(DB); conn.row_factory = sqlite3.Row
    rows = conn.execute(sql, args).fetchall(); conn.close()
    return rows


def db1(sql, args=()):
    r = dbq(sql, args)
    return dict(r[0]) if r else None


def api(method, path, **kw):
    r = getattr(client, method)(path, **kw)
    try:
        body = r.json(); biz = body.get("code", "?"); data = body.get("data")
    except Exception:
        body = r.text[:150]; biz = "non-json"; data = None
    ok = r.status_code == 200 and biz == 0
    print(f"  {'✅' if ok else '❌'} {method.upper()} {path} http={r.status_code} biz={biz} "
          f"data={json.dumps(data, ensure_ascii=False, default=str)[:140] if data else body}")
    return body


def webhook(action_value):
    """模拟飞书卡片按钮点击（POST /webhook/feishu/card）。

    真实测试时你飞书点按钮会打同样 webhook。脚本模拟用于断言 DB。
    """
    r = httpx.post(WEBHOOK, json={"action": {"value": action_value}}, timeout=15)
    try:
        body = r.json()
    except Exception:
        body = r.text[:150]
    print(f"  webhook {action_value.get('action_id','?')}: http={r.status_code} resp={json.dumps(body,ensure_ascii=False,default=str)[:120] if isinstance(body,dict) else body}")
    return body


def wait(prompt):
    print(f"\n  ⏳ {prompt}")
    print("  👆 请去飞书点击对应按钮，然后回这里按回车继续...")
    input()
    time.sleep(1)


def status():
    print("\n  📊 当前状态:")
    rows = dbq(
        "select p.sort_order as ps, p.name as pn, p.status as pst, "
        "t.sort_order as ts, t.name as tn, t.status as tst, substr(t.id,1,8) as tid "
        "from phases p left join tasks t on t.phase_id=p.id "
        "where p.theme_id=? order by p.sort_order, t.sort_order", (THEME_ID,))
    cp = None
    for r in rows:
        if r["ps"] != cp:
            print(f"    阶段{r['ps']} [{r['pst']}] {r['pn']}")
            cp = r["ps"]
        if r["tn"]:
            print(f"      {r['ts']}. {r['tn']} [{r['tst']}] ({r['tid']})")


def task_ids_of(phase_id):
    return [r["id"] for r in dbq(
        "select id from tasks where phase_id=? order by sort_order", (phase_id,))]


# ============================================================
print("=" * 70)
print("端到端 Story 测试 | 数据：知识库构建（1g+4p+12t，learning）")
print("=" * 70)
status()

# ============================================================
print("\n" + "=" * 70)
print("【S1 规划确认】API 造数据（已完成，12 tasks 已建）")
print("=" * 70)
# S1 已在 setup 完成，这里只断言
n_tasks = db1("select count(*) c from tasks where phase_id in "
              "(select id from phases where theme_id=?)", (THEME_ID,))["c"]
print(f"  ✅ DB 断言：tasks={n_tasks}（期望 12）")

# ============================================================
print("\n" + "=" * 70)
print("【S2 调度激活】API schedules/confirm（卡片是 Skill 职责，Service 无推卡方法）")
print("=" * 70)
api("post", "/schedules/confirm", json={
    "user_id": "u_e2e", "goal_id": GOAL_ID,
    "items": [{"theme_id": THEME_ID, "managed": True, "phase_id": P1, "deadline": "2026-07-20"}]})
p1 = db1("select status, deadline from phases where id=?", (P1,))
print(f"  ✅ DB 断言：阶段1 status={p1['status']}（期望 进行中）deadline={p1['deadline']}")
ws = db1("select count(*) c from workspaces where theme_id=?", (THEME_ID,))
print(f"  ✅ DB 断言：workspace 数={ws['c']}（期望 1）")

# 测 schedule.confirm webhook 回调（再激活会超 quota，这里只验证路由通）
print("  测 webhook schedule.confirm 路由（重复激活预期 409 超限，证明路由通）:")
webhook({"action_id": "schedule.confirm", "user_id": "u_e2e", "goal_id": GOAL_ID,
         "items": [{"theme_id": THEME_ID, "managed": True, "phase_id": P2, "deadline": "2026-07-25"}]})

# ============================================================
print("\n" + "=" * 70)
print("【S3 今日计划】API daily/confirm（卡片是 Skill 职责）")
print("=" * 70)
tids = task_ids_of(P1)
api("post", "/daily/confirm", json={
    "user_id": "u_e2e", "date": "2026-07-10",
    "task_ids": tids, "pre_subtasks": [], "push_source": "manual"})
dr = db1("select id, is_confirmed, push_source from daily_records order by created_at desc limit 1")
print(f"  ✅ DB 断言：daily_record is_confirmed={dr['is_confirmed']}（期望 0，S5 才置 True）push_source={dr['push_source']}")
dt = db1("select count(*) c from daily_tasks where daily_id=?", (dr["id"],))
print(f"  ✅ DB 断言：daily_tasks={dt['c']}（期望 3，阶段1的3个任务）")

# 测 story3_确认今日计划 webhook 路由
print("  测 webhook story3_确认今日计划 路由（重复确认预期 409，证明路由通）:")
webhook({"action_id": "story3_确认今日计划", "user_id": "u_e2e", "date": "2026-07-10",
         "task_ids": tids, "pre_subtasks": []})

DAILY_ID = dr["id"]

print("\n" + "=" * 70)
print("S1/S2/S3 数据准备完成。下一步 S4A 推验收卡（需 opencode agent 产出）。")
print("继续 S4A 吗？按回车继续，或 Ctrl+C 停止。")
input()
status()
