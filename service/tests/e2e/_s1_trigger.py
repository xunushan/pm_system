"""E2E S1 触发：真实 API 写 draft -> 兜底 Service 方法推方案总览卡。

纪律（TEST_PLAN §二）：
  - 数据准备走真实 API 入口（POST /api/v1/drafts），不直调 DraftAppSvc
  - 推卡走兜底 Service 方法（push_overview_card，Skill 缺位兜底，无 API 端点）
  - 确认动作必须由真实飞书点击触发（本脚本只推卡，不点按钮）

用法：DATABASE_URL=sqlite:///./data/e2e.db uv run python tests/e2e/_s1_trigger.py
"""

import httpx

from app.config import settings
from app.db.session import SessionLocal
from app.services.plan_app_svc import PlanAppSvc

API = "http://localhost:8001"

# vision 主数据（doc/09 映射：4 专题 × 1 阶段 × 3 任务 = 12 任务，全 learning）
PLAN_CONTENT = {
    "goal": {
        "name": "知识库构建",
        "description": "构建个人知识获取->沉淀->消费->回流闭环，支撑面试准备与项目决策",
        "time_range_start": "2026-07-01",
        "time_range_end": "2026-09-30",
        "scheduled_start_date": "2026-07-11",
    },
    "themes": [
        {
            "name": "知识获取",
            "type": "learning",
            "description": "信息获取渠道设计与去重",
            "phases": [
                {
                    "name": "阶段1：知识获取",
                    "sort_order": 1,
                    "tasks": [
                        {"name": "理论推导", "sort_order": 1, "description": "渠道设计与过滤机制"},
                        {
                            "name": "代码实现与工程化",
                            "sort_order": 2,
                            "description": "部署 RSSHub + 抓取 Pipeline",
                        },
                        {
                            "name": "总结+面试题库整理",
                            "sort_order": 3,
                            "description": "输出渠道矩阵与面试题",
                        },
                    ],
                }
            ],
        },
        {
            "name": "知识沉淀",
            "type": "learning",
            "description": "知识提炼方法论与笔记结构化",
            "phases": [
                {
                    "name": "阶段1：知识沉淀",
                    "sort_order": 1,
                    "tasks": [
                        {"name": "理论推导", "sort_order": 1, "description": "5C 评估与精读三阶段"},
                        {
                            "name": "代码实现与工程化",
                            "sort_order": 2,
                            "description": "笔记模板与归档系统",
                        },
                        {
                            "name": "总结+面试题库整理",
                            "sort_order": 3,
                            "description": "输出沉淀 SOP",
                        },
                    ],
                }
            ],
        },
        {
            "name": "知识库架构RAG",
            "type": "learning",
            "description": "Embedding 检索与 RAG 架构",
            "phases": [
                {
                    "name": "阶段1：知识库架构和RAG",
                    "sort_order": 1,
                    "tasks": [
                        {
                            "name": "理论推导",
                            "sort_order": 1,
                            "description": "向量检索算法与 RAG 链路",
                        },
                        {
                            "name": "代码实现与工程化",
                            "sort_order": 2,
                            "description": "部署 Embedding + 向量库",
                        },
                        {
                            "name": "总结+面试题库整理",
                            "sort_order": 3,
                            "description": "输出架构图与优化 checklist",
                        },
                    ],
                }
            ],
        },
        {
            "name": "知识管理闭环",
            "type": "learning",
            "description": "知识消费回流与生命周期管理",
            "phases": [
                {
                    "name": "阶段1：知识管理闭环",
                    "sort_order": 1,
                    "tasks": [
                        {"name": "理论推导", "sort_order": 1, "description": "消费推送与回流机制"},
                        {
                            "name": "代码实现与工程化",
                            "sort_order": 2,
                            "description": "实现查询接口与推送",
                        },
                        {
                            "name": "总结+面试题库整理",
                            "sort_order": 3,
                            "description": "输出闭环流程图",
                        },
                    ],
                }
            ],
        },
    ],
}


def main() -> None:
    # 1. 真实 API 入口写 draft
    resp = httpx.post(
        f"{API}/api/v1/drafts",
        json={
            "user_id": "feishu_user",
            "story_type": "plan",
            "content": PLAN_CONTENT,
        },
        timeout=10,
    )
    resp.raise_for_status()
    draft_id = resp.json()["data"]["draft_id"]
    print(f"[OK] draft 写入成功 (真实 API): draft_id = {draft_id}")

    # 2. 兜底推卡（Skill 缺位，直调 Service 推卡方法）
    chat_id = settings.feishu_default_chat_id
    with SessionLocal() as db:
        message_id = PlanAppSvc(db).push_overview_card(
            goal_name="知识库构建",
            theme_count=4,
            phase_count=4,
            task_count=12,
            draft_id=draft_id,
            chat_id=chat_id,
        )
    if not message_id:
        raise SystemExit("[FAIL] send_card 未返回 message_id（检查飞书配置）")
    print(f"[OK] 方案总览卡已推送: message_id = {message_id}")
    print()
    print(">>> 请在飞书点击「确认方案」按钮，然后运行 _s1_verify.py 验证 <<<")
    print(f">>> draft_id={draft_id}")
    print(f">>> message_id={message_id}")


if __name__ == "__main__":
    main()
