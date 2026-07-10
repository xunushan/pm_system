"""端到端测试数据准备：用真实规划内容（知识库构建）造 goal/theme/phase/task 树。

跳过 Skill 引导，直接 API 造数据。返回所有 id 供后续测试脚本用。
"""
import json
import sqlite3

import httpx

BASE = "http://127.0.0.1:8001/api/v1"
DB = "data/e2e.db"  # 端到端测试用 e2e.db（真实文件，不碰开发库）
client = httpx.Client(base_url=BASE, timeout=15)


def step(name, r):
    code = r.status_code
    try:
        body = r.json(); biz = body.get("code", "?"); data = body.get("data")
    except Exception:
        body = r.text[:200]; biz = "non-json"; data = None
    ok = code == 200 and biz == 0
    print(f"{'✅' if ok else '❌'} [{name}] http={code} biz={biz} data={json.dumps(data, ensure_ascii=False, default=str)[:150] if data else body}")
    return body


# ===== 测试数据：知识库构建（来自 ~/Downloads/vision-知识库构建.md）=====
PLAN = {
    "goal": {
        "name": "知识库构建",
        "description": "构建个人知识获取->知识库提炼->知识消费->知识回流闭环，支撑面试准备与项目决策",
        "time_range_start": "2026-07-01",
        "time_range_end": "2026-09-30",
        "scheduled_start_date": "2026-07-10",
    },
    "themes": [
        {
            "name": "知识库构建",
            "type": "learning",  # learning -> executor 推断 human，便于走 S4B 人完成
            "phases": [
                {
                    "name": "阶段1：知识获取",
                    "sort_order": 1,
                    "tasks": [
                        {"name": "理论推导", "sort_order": 1},
                        {"name": "代码实现与工程化", "sort_order": 2},
                        {"name": "总结+面试题库整理", "sort_order": 3},
                    ],
                },
                {
                    "name": "阶段2：知识沉淀",
                    "sort_order": 2,
                    "tasks": [
                        {"name": "理论推导", "sort_order": 1},
                        {"name": "代码实现与工程化", "sort_order": 2},
                        {"name": "总结+面试题库整理", "sort_order": 3},
                    ],
                },
                {
                    "name": "阶段3：知识库架构和RAG",
                    "sort_order": 3,
                    "tasks": [
                        {"name": "理论推导", "sort_order": 1},
                        {"name": "代码实现与工程化", "sort_order": 2},
                        {"name": "总结+面试题库整理", "sort_order": 3},
                    ],
                },
                {
                    "name": "阶段4：知识管理闭环",
                    "sort_order": 4,
                    "tasks": [
                        {"name": "理论推导", "sort_order": 1},
                        {"name": "代码实现与工程化", "sort_order": 2},
                        {"name": "总结+面试题库整理", "sort_order": 3},
                    ],
                },
            ],
        }
    ],
}

print("===== S1: 规划确认（造知识库构建目标树）=====")
r = client.post("/drafts", json={"user_id": "u_e2e", "story_type": "plan", "content": PLAN})
draft_id = r.json()["data"]["draft_id"]
r = client.post("/plans/confirm", json={"draft_id": draft_id})
s1 = step("plans/confirm", r)
goal_id = s1["data"]["goal_id"]
print(f"  goal_id={goal_id}")

# 查所有 id
conn = sqlite3.connect(DB); conn.row_factory = sqlite3.Row
theme_id = conn.execute("select id from themes where goal_id=?", (goal_id,)).fetchone()["id"]
phases = conn.execute("select id, sort_order, name, status from phases where theme_id=? order by sort_order", (theme_id,)).fetchall()
print(f"\n  theme_id={theme_id}")
print("  阶段:")
phase_ids = {}
for p in phases:
    phase_ids[p["sort_order"]] = p["id"]
    tasks = conn.execute("select id, sort_order, name, status from tasks where phase_id=? order by sort_order", (p["id"],)).fetchall()
    task_info = ", ".join(f"{t['name']}({t['id'][:8]})" for t in tasks)
    print(f"    {p['name']} [{p['status']}] -> {task_info}")

# 写 id 到文件供后续脚本
ids = {
    "goal_id": goal_id,
    "theme_id": theme_id,
    "phase_ids": phase_ids,  # {1: id, 2: id, ...}
}
with open("/tmp/e2e_test_ids.json", "w") as f:
    json.dump(ids, f, indent=2, ensure_ascii=False)
print(f"\n  id 已写 /tmp/e2e_test_ids.json")
print(f"  造数据完成：1 goal + 1 theme + 4 phases + 12 tasks")
