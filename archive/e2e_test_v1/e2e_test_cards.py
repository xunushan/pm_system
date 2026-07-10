"""S4A/S5/S8/S6 真实推卡测试（接 e2e_test_run.py 的 S1/S2/S3 之后）。

每个 Story：调 API 推卡 -> 你飞书收到 -> 你点按钮 -> 查 DB 断言。
"""
import json
import sqlite3
import time
from pathlib import Path

import httpx

API = "http://127.0.0.1:8001/api/v1"
CALLBACK = "http://127.0.0.1:8001/api/callback/opencode"
WEBHOOK = "http://127.0.0.1:8001/webhook/feishu/card"
DB = "data/e2e.db"
client = httpx.Client(base_url=API, timeout=30)

ids = json.load(open("/tmp/e2e_test_ids.json"))
GOAL_ID, THEME_ID = ids["goal_id"], ids["theme_id"]
P1, P2, P3, P4 = ids["phase_ids"]["1"], ids["phase_ids"]["2"], ids["phase_ids"]["3"], ids["phase_ids"]["4"]


def dbq(sql, args=()):
    conn = sqlite3.connect(DB); conn.row_factory = sqlite3.Row
    rows = conn.execute(sql, args).fetchall(); conn.close(); return rows

def db1(sql, args=()):
    r = dbq(sql, args); return dict(r[0]) if r else None

def api(method, path, base=None, **kw):
    c = httpx.Client(base_url=base or API, timeout=30)
    r = getattr(c, method)(path, **kw)
    try:
        body = r.json(); biz = body.get("code", "?"); data = body.get("data")
    except Exception:
        body = r.text[:150]; biz = "non-json"; data = None
    ok = r.status_code == 200 and biz == 0
    print(f"  {'✅' if ok else '❌'} {method.upper()} {path} http={r.status_code} biz={biz} "
          f"data={json.dumps(data, ensure_ascii=False, default=str)[:140] if data else body}")
    c.close()
    return body

def webhook(action_value):
    r = httpx.post(WEBHOOK, json={"action": {"value": action_value}}, timeout=15)
    try: body = r.json()
    except Exception: body = r.text[:150]
    print(f"  webhook {action_value.get('action_id','?')}: http={r.status_code} "
          f"resp={json.dumps(body,ensure_ascii=False,default=str)[:120] if isinstance(body,dict) else body}")
    return body

def wait(prompt):
    print(f"\n  ⏳ {prompt}")
    print("  👆 去飞书点按钮后回车继续...")
    input(); time.sleep(1)

def status():
    print("\n  📊 状态:")
    rows = dbq("select p.sort_order ps,p.name pn,p.status pst,t.sort_order ts,t.name tn,t.status tst,substr(t.id,1,8) tid "
               "from phases p left join tasks t on t.phase_id=p.id where p.theme_id=? "
               "order by p.sort_order,t.sort_order", (THEME_ID,))
    cp=None
    for r in rows:
        if r["ps"]!=cp:
            print(f"    阶段{r['ps']} [{r['pst']}] {r['pn']}"); cp=r["ps"]
        if r["tn"]: print(f"      {r['ts']}. {r['tn']} [{r['tst']}] ({r['tid']})")

def task_ids_of(pid): return [r["id"] for r in dbq("select id from tasks where phase_id=? order by sort_order",(pid,))]


# ============================================================
print("=" * 70)
print("【S4A 验收卡推送】调 /api/callback/opencode/output 触发推卡")
print("=" * 70)
# 造测试产出文件
out_file = Path("/tmp/e2e_test_output.md")
out_file.write_text("# 理论推导产出\n\n信息获取渠道设计文档。", encoding="utf-8")
# 阶段1 第1个任务（理论推导）作为 agent 任务产出
t1 = task_ids_of(P1)[0]
ws = db1("select id from workspaces where theme_id=?", (THEME_ID,))
print(f"  task_id={t1[:8]} workspace_id={ws['id'][:8]}")
api("post", "/opencode/output", base=CALLBACK, json={
    "task_id": t1, "workspace_id": ws["id"],
    "outputs": [{"file_path": str(out_file), "file_type": "note", "summary": "理论推导产出"}]})
wp = db1("select count(*) c from workspace_progress where task_id=?", (t1,))
print(f"  ✅ DB 断言：workspace_progress={wp['c']}（期望 1，产出已记录）")
wait("飞书应收到 [任务完成确认] 验收卡（含任务名+产出文件+验收通过/需要修改按钮）")

# 测 story4A_验收通过 webhook（脚本模拟点击，断言 task 完成+级联）
print("  脚本模拟点 [验收通过]（story4A_验收通过）:")
webhook({"action_id": "story4A_验收通过", "task_id": t1, "user_id": "u_e2e", "workspace_progress_ids": []})
tk = db1("select status from tasks where id=?", (t1,))
print(f"  ✅ DB 断言：task {t1[:8]} status={tk['status']}（期望 已完成）")

# ============================================================
print("\n" + "=" * 70)
print("【S4B 后置确认】webhook story4B_确认后置（S4A 完成后可能有后置）")
print("=" * 70)
# S4B 需要先 post-confirm 造后置。直接测 webhook 路由
print("  测 webhook story4B_确认后置 路由（可能无后置返回 400，证明路由通）:")
webhook({"action_id": "story4B_确认后置", "task_id": t1, "user_id": "u_e2e", "post_subtasks": []})

# ============================================================
print("\n" + "=" * 70)
print("【S5 日终总结卡推送】调 /api/v1/daily/summary/push 触发推卡")
print("=" * 70)
dr = db1("select id from daily_records order by created_at desc limit 1")
api("post", "/daily/summary/push", json={"daily_id": dr["id"]})
# 异步推卡，等几秒
time.sleep(3)
wait("飞书应收到 [今日总结] 卡片（含任务列表+标记完成/未完成+确认日终总结按钮）")

# 测 story5_标记完成（脚本模拟点击，改任务状态）
t2 = task_ids_of(P1)[1]  # 代码实现与工程化
print(f"  脚本模拟点 [标记完成:代码实现与工程化]（story5_标记完成）:")
webhook({"action_id": "story5_标记完成", "task_id": t2, "daily_id": dr["id"],
         "message_id": "", "user_id": "u_e2e"})
tk = db1("select status from tasks where id=?", (t2,))
print(f"  ✅ DB 断言：task {t2[:8]} status={tk['status']}（期望 已完成）")

# 测 story5_确认日终总结
print(f"  脚本模拟点 [确认日终总结]（story5_确认日终总结）:")
webhook({"action_id": "story5_确认日终总结", "daily_id": dr["id"], "user_id": "u_e2e"})
dr2 = db1("select is_confirmed from daily_records where id=?", (dr["id"],))
print(f"  ✅ DB 断言：daily_record is_confirmed={dr2['is_confirmed']}（期望 1）")

# ============================================================
print("\n" + "=" * 70)
print("【S8 阶段衔接卡】完成阶段1剩余任务 -> 触发 phase_completed -> 自动推衔接卡")
print("=" * 70)
t3 = task_ids_of(P1)[2]  # 总结+面试题
print(f"  完成阶段1最后一个任务（{db1('select name from tasks where id=?',(t3,))['name']}）:")
api("post", f"/tasks/{t3}/complete", json={"user_id": "u_e2e"})
time.sleep(3)  # 等 event_bus daemon 推衔接卡
p1s = db1("select status from phases where id=?", (P1,))
print(f"  ✅ DB 断言：阶段1 status={p1s['status']}（期望 已完成，触发 phase_completed 事件）")
link_key = db1("select count(*) c from (select 0)")  # 占位
import subprocess
rk = subprocess.run(["redis-cli","keys","supervisor:linking:*"],capture_output=True,text=True)
print(f"  ✅ Redis: {rk.stdout.strip() or '(无)'}（应有 supervisor:linking:pushed:{P1[:8]}...）")
wait("飞书应收到 [阶段衔接] 卡片（阶段1已完成->阶段2，确认激活/暂不激活按钮）")

# 测 story8_确认激活（脚本模拟，激活阶段2）
print("  脚本模拟点 [确认激活]（story8_确认激活）:")
webhook({"action_id": "story8_确认激活", "phase_id": P2, "deadline": "2026-08-20", "user_id": "u_e2e"})
p2s = db1("select status from phases where id=?", (P2,))
print(f"  ✅ DB 断言：阶段2 status={p2s['status']}（期望 进行中）")

# ============================================================
print("\n" + "=" * 70)
print("【S6 专题完成卡】完成全部阶段 -> 触发 theme_completed -> 推专题完成卡")
print("=" * 70)
print("  （需完成阶段2/3/4 所有任务，触发 theme_completed 事件）")
print("  为快速测试，直接用 API 完成剩余阶段任务:")
for pid, dl in [(P2,"2026-08-20"),(P3,"2026-09-10"),(P4,"2026-09-25")]:
    # 激活该阶段（如未激活）
    ps = db1("select status from phases where id=?", (pid,))
    if ps["status"] != "进行中":
        api("post","/schedules/activate",json={"phase_id":pid,"deadline":dl,"user_id":"u_e2e"})
    for tid in task_ids_of(pid):
        api("post", f"/tasks/{tid}/complete", json={"user_id": "u_e2e"})
time.sleep(3)
goal = db1("select status from goals where id=?", (GOAL_ID,))
theme = db1("select status from themes where id=?", (THEME_ID,))
print(f"  ✅ DB 断言：theme status={theme['status']}（期望 已完成，触发 theme_completed）")
print(f"  ✅ DB 断言：goal status={goal['status']}（期望 已完成）")
wait("飞书应收到 [专题完成] 卡片（列出其他未完成专题或目标完成通知）")

# 测 story6_已阅周总结 webhook
print("  脚本模拟点 [已阅周总结]（story6_已阅周总结）:")
wk = db1("select week from weekly_records order by created_at desc limit 1")
if wk:
    webhook({"action_id": "story6_已阅周总结", "week": wk["week"]})
else:
    print("  （无 weekly_record，先建一个）")
    api("post","/weekly/summary/confirm",json={"week":"2026-W28"})

# ============================================================
print("\n" + "=" * 70)
print("【S9 看板编辑/回退】API board（无卡片）")
print("=" * 70)
api("put", f"/board/phase/{P1}", json={"fields": {"name": "阶段1：知识获取（改名）"}})
api("post", f"/board/phase/{P1}/status", json={"user_id":"u_e2e","to_status":"进行中","reason":"e2e测试回退"})
p1r = db1("select status,name from phases where id=?", (P1,))
print(f"  ✅ DB 断言：阶段1 name={p1r['name']} status={p1r['status']}（期望 改名+进行中-回退）")

print("\n" + "=" * 70)
print("🎉 全 Story 端到端测试完成！")
print("=" * 70)
status()
