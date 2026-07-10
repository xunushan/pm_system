# 开发进度

> 详细历史见 `archive/PROGRESS_v1_history.md`（9/9 Story 开发 + 端到端验证 v1 全记录，仅供审计）。

## 当前状态（2026-07-10）

服务层 9/9 Story 已合并 main（539 测试绿，7 迁移，14 表）。端到端卡片交互测试 v1 暴露 6 个问题，已归档，现进入 v2。

## v1 交代（为何重来）

首轮端到端卡片测试失败，核心问题：
1. **架构理解错**：卡片构建/推送应是 Service 职责，非 Skill。S2/S3/S6/S8 缺 Service 推卡入口。
2. **卡片点击后不更新**：webhook 回调后不 update_card，用户看到旧卡、按钮可重复点、状态无反馈。
3. **卡片样式问题**：按钮堆一起不挨任务，点击后状态在卡上不变。
4. **测试作弊**：脚本模拟点击 + 手动改 DB，掩盖失败。
5. **opencode 未启动**：S4A 执行链依赖 opencode serve，测试时没起。
6. **S1 未走 draft 流程**：直接 plans/confirm，draft 表空。

旧脚本见 `archive/e2e_test_v1/`，v1 临时改动已 stash（`e2e-v1: chat_id fix + push_daily_summary entry`）。

## v2 计划（进行中）

原则：Service 封装卡片全链路（构建+推送+回调+点击后 update_card 重构整张卡），真实 opencode，按 Story 顺序不跳，禁止改 DB，真实点击。

### v2 前置改造（拆小 PR 逐个）

- [ ] **PR-1**：chat_id_placeholder 修复（task_app_svc 4 处硬编码 -> DEFAULT_CHAT_ID，v1 stash 里有）
- [ ] **PR-2**：卡片更新机制（webhook 回调后 update_card 重构整张卡）+ 样式重构（按钮挨任务、状态体现）
- [ ] **PR-3**：Service 推卡入口补全（S2/S3/S6/S8）
- [ ] **PR-4**：S1 draft 真实流程 + opencode serve 启动脚本

### v2 测试计划（按 Story 顺序，纠正后）

| Story | 卡片 | 推卡触发 | 点击场景 | 点击后 | DB 断言 |
|-------|------|---------|---------|--------|---------|
| S1 | 总览卡（draft 确认） | Service push | 确认方案 | update_card 置灰 | draft 写入+落库+删 |
| S2 | 调度激活卡 | Service push | 确认调度 | update_card | phase 激活+workspace |
| S3 | 今日计划卡 | Service push | 确认今日计划 | update_card | daily_records 写入 |
| S4A | 验收卡 | opencode 产出触发 | **场景1 验收通过** + **场景2 需要修改（feedback 输入框）** | update_card | task 完成+级联 / 重试 |
| S4B | 任务完成确认卡（带后置勾选） | Service push | 确认后置 / 不需要后置 | update_card | 后置 subtasks |
| S5 | 日终总结卡 | Service push | 标记完成/未完成 + 确认日终总结 | update_card 实时更新 | task 状态+is_confirmed |
| S6 | 周总结卡（周日 12:00 定时） | scheduler 定时 | 已阅 | update_card 置灰 | weekly_records+weekly.md |
| S8 | 阶段衔接卡 | supervisor phase_completed 事件 | 确认激活/暂不激活 | update_card | phase 激活 |
| S9 | 无卡 | board API | - | - | board 编辑/回退 |

**纠正（v1 误读 doc/01）**：
- S4B 是「任务完成确认卡」（人执行任务完成后推，卡里带后置勾选），不是"后置确认卡"。缺 builder。
- S4A 两个场景：验收通过 + 需要修改（feedback 输入框，v1 移除了，PR-2 补回）。
- S6 是周总结卡（周日 12:00 定时推），不是 build_theme_completed（那是 S8 衔接，theme_completed 事件）。S6 和 supervisor 仅数据参考（下周建议参考衔接状态）。缺 builder + scheduler 定时。

**v2 前置改造需补的 builder**：
- S4B `build_task_complete_card`（任务完成确认 + 后置勾选 + 确认/不需要按钮）
- S6 `build_weekly_summary_card`（周总结，含每日回顾/阶段健康/产出/下周建议 + 已阅按钮）
- S4A `build_verification_card` 补回 feedback input 组件（issue #20）

### v2 进度

- [ ] 前置改造（PR-1 ~ PR-4）
- [ ] S1-S9 逐项测试（真实点击，禁止改 DB）

## 关键参考

- `archive/PROGRESS_v1_history.md`：9/9 Story 开发全记录 + 端到端 v1 验证（审计）
- `archive/e2e_test_v1/`：v1 测试脚本（已废弃）
- 设计文档 `doc/`（只读）
- P0 opencode 重写方案见 `archive/e2e_test_v1/P0_opencode_修复方案.md`（已实现，PR #19 合并）
