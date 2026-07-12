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

### 对齐（文档/规范层）- 已完成
- [x] D25 卡片全生命周期归 Service -> doc/07
- [x] 同步 doc/03 §1.2（消除「❌ Service」一刀切）
- [x] CLAUDE.md 铁律加第 11 条（卡片全生命周期归 Service）
- [x] 新建 doc/08 教训文档（含测试三分概念划分）
- [x] D26 进程模型修正（方案 B 单进程多 session）+ Story4A 确认完成推卡 -> doc/07
- [x] D17 进程描述修正（doc/07 就地标注）
- [x] doc/06 Story4A 步骤8/9 改写（退 session + 确认完成推卡）
- [x] doc/09 卡片交互样式记录（全 Story schema 2.0 实证 + 验证记录 V1-V9 + 飞书链接）
- [x] CLAUDE.md 铁律8 补 executor 可改 + 复用件表 opencode 方案 B 说明

### 修复（代码层）- 已完成
- [x] **FIX-1**：S5 message_id 双保险取法框架已合（PR #23）；⚠️ 但 PR #23 取的是顶层 `payload.get("open_message_id")`，实测正确路径是 `payload["event"]["context"]["open_message_id"]`（doc/09 V2），正确路径修正归入 PR-C
- [x] **FIX-2**：S4A 主任务下发（daily_app_svc 传 task，PR #23 已合）
- [x] **PR-1**：chat_id_placeholder 修复（PR #22 已合）

### schema 2.0 卡片改造（进行中，详见 doc/09）
> 全局 builder 从旧版（config+elements）升级到 schema 2.0（schema+body.elements），支持 form/checker/date_picker。所有交互样式已在 doc/09 实证。

- [ ] **代码缺口-0**：opencode.py 补 `delete_session(session_id)`（调 `DELETE /session/:sessionID`），3 次不通过时退 session（D26）
- [ ] **PR-A**：FeishuClient 适配 + 现有 9 builder 改 schema 2.0（build_verification_card/build_daily_summary_card/build_phase_linking_card 等）+ 测试改新版结构
- [ ] **PR-B**：补 5 个新 builder（build_plan_overview_card/build_schedule_card_a+b/build_daily_plan_card/build_task_complete_card/build_weekly_summary_card）+ 测试
- [ ] **PR-C**：补 Service 推卡入口（PlanAppSvc.push_overview_card/ScheduleAppSvc.push_schedule_card/DailyAppSvc.push_daily_plan_card/WeeklyAppSvc.push_weekly_summary_card）+ story1_确认方案 + story2_下一步 webhook handler + **feishu_card.py 取法修正（message_id 路径 payload["event"]["context"]["open_message_id"] 修正 FIX-1 错误取顶层 + form_value + name 路由）**
- [ ] **PR-D**：全回调 update_card 补全（12 回调点击后刷新）+ form_value 处理（date_picker/checker/multi_select/input）+ delete_session 调用 + 测试

合并顺序：PR-A -> PR-B -> PR-C -> PR-D（串行，依赖）。

### 端到端验证（schema 2.0 改造完成后）
- [ ] tests/e2e/TEST_PLAN.md 更新为 schema 2.0 用例（已建，需对齐 doc/09 样式）
- [ ] tests/e2e/test_infra.py 冒烟（token/推卡/回调到达/opencode 起/redis ping）
- [ ] 起真实 opencode serve（port 18800）
- [ ] S1 -> S9 逐项真测（真实推卡 + 真实点击 + 禁止改 DB + 真实 opencode，按 doc/09 样式验证）

### 进度日志
- 2026-07-10：复盘完成（七问 + 3 agent 证据），文档对齐落地（D25/doc/08/doc/03/CLAUDE.md）。
- 2026-07-10：FIX-1+2 完成（PR #23 合并）。
- 2026-07-11：飞书卡片 schema 2.0 调研，全 Story 卡片交互样式实证（doc/09）。D26 进程模型修正 + Story4A 确认完成推卡。下一步按 PR-A~D 推进 schema 2.0 改造。

## 四、参考索引（只放链接，不抄内容）

- 设计决策：`doc/07_决策文档_v1.0.md`（D1-D26）
- 教训：`doc/08_教训文档.md`（L1-L6 + 测试三分 + 行业标准）
- 卡片交互样式（schema 2.0）：`doc/09_卡片交互样式记录.md`（全 Story JSON + 验证记录 + 飞书链接）
- e2e 测试用例：`service/tests/e2e/TEST_PLAN.md`（第③步建）
- v1 完整历史：`archive/PROGRESS_v1_history.md`
- v1 测试脚本（废弃）：`archive/e2e_test_v1/`
- 设计文档：`doc/`（只读）
- 代码进度表：`service/app/models/__init__.py` 的 ✅/⬜
- 测试三分与 CI 门禁：doc/08 第二节
