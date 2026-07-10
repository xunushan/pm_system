# 开发进度

> 本文件只维护"阶段状态 + 上阶段关键问题(精简) + 当前计划追踪区(高频更新) + 参考索引"。
> 详情不抄这里：决策见 doc/07，教训见 doc/08，e2e 用例见 tests/e2e/TEST_PLAN.md，v1 历史见 archive/。

## 一、阶段状态

- **上一阶段**：Service 开发 9/9 Story 合并 main（539 测试绿，7 迁移，14 表）+ 6 修复 PR。端到端验证 v1 全 Story 卡片交互不合格。
- **当前阶段**：v2 修复 + 端到端验证（进行中）
- **完成信号**：每个含卡 Story = unit/integration 绿(CI) + 契约绿(CI) + e2e 该 Story 用例真跑过(手动)。三者齐全才算完成。

## 二、上阶段关键问题（精简，详见 doc/08）

| # | 问题 | 性质 | 详见 |
|---|------|------|------|
| 1 | 设计文档对"卡片归谁"自相矛盾，子 agent 选错边 | 根因 | doc/08 L1 / doc/07 D25 |
| 2 | 495 测试全绿 ≠ 系统能用（测试金字塔缺 e2e 顶层）| 根因 | doc/08 L2 |
| 3 | 卡片结构测只查 dict 键，飞书拒收才发现 | 缺口 | doc/08 L3 |
| 4 | 基础设施(webhook/redis/app_id)最后才配，全程无真实反馈 | 根因 | doc/08 L4 |
| 5 | 测试脚本绕真实入口 + 手改 DB 掩盖失败 | 方法错 | doc/08 L5 |
| 6 | 异步副作用(update_card)被 mock 掉且不断言 | 缺口 | doc/08 L6 |
| 7 | S5 update_card 坏：build_daily_summary_card 的 value 不含 message_id，回调取恒空 | 真 bug | FIX-1 |
| 8 | S4A 主任务不下发：daily_app_svc.py:399 start_agent_serve 不传 task | 真 bug | FIX-2 |

完整 v1 历史：`archive/PROGRESS_v1_history.md`（审计用）。

## 三、当前阶段计划与追踪（唯一高频更新区）

### 对齐（文档/规范层）— 已完成
- [x] D25 卡片全生命周期归 Service -> doc/07
- [x] 同步 doc/03 §1.2（消除「❌ Service」一刀切）
- [x] CLAUDE.md 铁律加第 11 条
- [x] 新建 doc/08 教训文档（含测试三分概念划分）

### 修复（代码层）
- [ ] **FIX-1**：S5 message_id 传递（build_daily_summary_card 的 button value 写入 message_id；回调读取）
- [ ] **FIX-2**：S4A 主任务下发（daily_app_svc.py:399 传 task 参数给 start_agent_serve）
- [ ] **FIX-3**：补 5 个 builder（S1 总览/S2 调度/S3 今日计划/S4B 任务完成/S6 周总结）
- [ ] **FIX-4**：补 Service 推卡入口（S2 ScheduleAppSvc / S3 DailyAppSvc / S6 WeeklyAppSvc / S1）
- [ ] **FIX-5**：全回调 update_card 统一（按钮灰化/反转/消失）+ 按钮挨任务 per-item 样式
- [ ] **PR-1**（独立小修）：chat_id_placeholder 修复（task_app_svc 4 处 -> DEFAULT_CHAT_ID）

### 端到端验证
- [ ] tests/e2e/TEST_PLAN.md 定稿（每用例 7 字段：前置/数据准备/步骤/卡片预期/DB预期/禁止项/通过判据）
- [ ] tests/e2e/test_infra.py 冒烟（token/推卡/回调到达/opencode 起/redis ping）
- [ ] 起真实 opencode serve（port 18800）
- [ ] S1 -> S9 逐项真测（真实推卡 + 真实点击 + 禁止改 DB + 真实 opencode）

### 进度日志
- 2026-07-10：复盘完成（七问 + 3 agent 证据），文档对齐落地（D25/doc/08/doc/03/CLAUDE.md）。

## 四、参考索引（只放链接，不抄内容）

- 设计决策：`doc/07_决策文档_v1.0.md`（D1-D25）
- 教训：`doc/08_教训文档.md`（L1-L6 + 测试三分 + 行业标准）
- e2e 测试用例：`service/tests/e2e/TEST_PLAN.md`（第③步建）
- v1 完整历史：`archive/PROGRESS_v1_history.md`
- v1 测试脚本（废弃）：`archive/e2e_test_v1/`
- 设计文档：`doc/`（只读）
- 代码进度表：`service/app/models/__init__.py` 的 ✅/⬜
- 测试三分与 CI 门禁：doc/08 第二节
