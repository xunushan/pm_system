# 端到端测试 v1 归档（2026-07-10）

> 第一轮端到端测试的脚本和方案，已废弃归档，仅供审计参考。**问题见下，新计划见 PROGRESS.md / 后续。**

## v1 方案缺陷（用户反馈，已确认）

1. **Skill 推卡职责理解错误**：以为卡片拼装是 Skill 职责（Skill 用 CardKit 拼），Service 只提供数据。**实际应为：Service 封装卡片构建+推送+回调全链路，Skill 只调 Service**。导致 S2/S3/S6/S8 缺 Service 推卡入口，测试时只能手动构卡，掩盖真实流程缺失。

2. **卡片点击后不更新**：webhook 回调处理后不 update_card，导致：
   - 用户点击后看到的还是原卡片，按钮可重复点击
   - 卡片上任务状态无变化（点了"标记完成"卡片不反映）
   - 只有 S5 异议有 refresh_summary_card_async（update_card），其他卡片都没有

3. **卡片样式问题**（以日终总结卡为例）：
   - 所有"标记完成/未完成"按钮和"确认日终总结"按钮堆在同一个 action block，排在一起
   - 按钮不挨着对应任务（应每任务一组按钮）
   - 点击后任务状态在卡片上无变化（不 update_card）

4. **测试过程作弊**：用脚本模拟点击 + 手动改 DB（填 executor、改 task 状态），掩盖真实失败。**真实测试不允许手动改 DB**。

5. **opencode 未启动**：S4A 智能体执行链依赖 opencode serve，但测试时 opencode 没起，retry/dispatch 全失败被忽略。

6. **S1 草稿未写 draft 表**：测试数据准备直接 plans/confirm，没走"先写 draft 再 confirm"的真实流程，draft 表空。

## 归档文件

- `e2e_test_setup.py`：造数据脚本（直接 API，跳过 draft）
- `e2e_test_run.py`：S1/S2/S3 测试脚本（含手动改 DB）
- `e2e_test_cards.py`：S4A/S5/S8/S6 测试脚本（含脚本模拟点击）
- `e2e_test_ids.json`：测试数据 id
- `P0_opencode_修复方案.md`：opencode 重写方案（已实现，PR #19 已合并，保留参考）

## v1 实际验证通过的（仅 Service 层 API + DB，非真实卡片流程）

- S1 plans/confirm 落库（但 draft 流程缺失）
- S2 schedules/confirm 激活级联
- S3 daily/confirm 写 daily_records/daily_tasks
- S4A output_confirm task->已完成（webhook 路由通）
- S5 patch_status 异议双向 forward/revert + confirm_summary
- supervisor phase_completed 事件 -> Redis 记录

## v1 未真正验证（被掩盖的失败）

- 所有卡片点击后的视觉反馈（不 update_card）
- 卡片样式（按钮布局问题）
- S4A opencode 真实执行链（opencode 没起）
- S2/S3/S6/S8 的 Service 推卡入口（缺失，手动构卡掩盖）
- S1 draft 真实流程
