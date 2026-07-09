# 开发进度

> 实时状态看板。**git 是真相源**，本文件是缓存。
> 当本文件与 git/PR/issue 状态矛盾时，以 git 为准并顺手更新本文件。
> 恢复协议见 CLAUDE.md「会话恢复协议」。

## 总顺序（依赖图）

```
S1 规划（基石）
  └─> { S2 调度 ‖ S7 子任务配置 }   ← 并行窗口 1
        └─> S3 今日计划
              └─> { S4A 智能体执行 ‖ S4B 人完成 }   ← 并行窗口 2
                    └─> { S5 日终总结 ‖ S6 周总结 }   ← 并行窗口 3
                          └─> S8 主动巡检
                                └─> S9 轻量编辑
```

串行点：S1 → S3 → S8 → S9 必须单独做。
并行窗口：{S2‖S7}、{S4A‖S4B}、{S5‖S6} 最多 2 并行。

## 状态表

| Story | 状态 | 分支 | PR | 负责人 | 依赖 | 阻塞 |
|-------|------|------|----|--------|------|------|
| S1 目标规划与确认 | ✅已合并 | - | #1 | - | 无 | - |
| S2 调度激活 | ✅已合并 | - | #2 | - | S1 | - |
| S3 今日计划推送 | ✅已合并 | - | #3 | - | S2 | - |
| S4A 智能体执行 | ✅已合并 | - | #5 | - | S3 | - |
| S4B 人完成任务 | ✅已合并 | - | #4 | - | S3 | - |
| S5 日终总结 | ⬜未开始 | - | - | - | S4B | - |
| S6 周总结 | ⬜未开始 | - | - | - | S5 | - |
| S7 子任务配置 | ⬜未开始 | - | - | - | S1 | - |
| S8 主动巡检 | ⬜未开始 | - | - | - | S5,S6 | - |
| S9 轻量编辑与回退 | ⬜未开始 | - | - | - | S8 | - |

状态图例：⬜未开始 / 🔄进行中 / 🔍审查中 / ✅已合并 / ⛔阻塞

## 更新规则

- **开始 Story**：建分支 `feat/story-N` -> 改状态 🔄，填分支名。
- **开 PR**：填 PR 号，状态改 🔍。
- **合并**：状态改 ✅，清空分支名（已删），记 PR 号。
- **遇阻塞**：状态 ⛔，阻塞列写明原因（如"等 S1 合并"）。
- **每次合并后**：主会话更新本文件 + 同步检查下游 Story 是否解锁。

## 合并历史

| Story | PR | 合并 commit | 日期 | 测试 | 备注 |
|-------|----|-------------|------|------|------|
| S1 目标规划与确认 | #1 | a6a34d3 | 2026-07-09 | 90 passed | themes/phases/tasks/drafts 4 model + 首迁移(5表6索引) + repo + DraftAppSvc/PlanAppSvc.confirm + drafts/plans 路由 + emit 桩；review 2×P1 已修 |
| S2 调度激活 | #2 | cd8f7b8 | 2026-07-09 | 137 passed | workspaces+status_change_log 2 model + 第2迁移(2表3索引) + cascade激活级联/state_machine forward/audit 实现 + ScheduleAppSvc.confirm(≤3/自动锁定/级联/审计/异步初始化) + WorkspaceAppSvc + schedules/workspaces路由 + webhook schedule.confirm；S2提前建审计表(铁律§3#7)；review P2-1(错误码1004)/P2-2(path校验前置事务外)已修 |
| S3 今日计划推送 | #3 | 8251237 | 2026-07-09 | 168 passed | daily_records+daily_tasks+subtasks(提前建) 3 model + 第3迁移(3表5索引) + DailyAppSvc(pool只读查询+confirm事务INSERT三表+异步opencode桩) + opencode dispatch/start_serve 桩(接口先行S4A换) + daily路由 + webhook story3确认；张力1(前置锚定首个human任务保持task_id NOT NULL)/张力2(opencode桩)处理合理；review 无P0P1 |
| S4B 人完成任务 | #4 | 0ad66b2 | 2026-07-09 | 219 passed | 补全 cascade 完成级联(§2.15完成链 task->phase->theme->goal) + state_machine task forward(待执行->已完成) + TaskAppSvc(complete完成级联/post_confirm后置/create_subtask+patch_subtask CRUD) + subtasks路由 + webhook story4B后置；S4B先合(S4A依赖其完成级联)；review P2-1(create_subtask校验executor)/P2-2(patch状态流转)已修 |
| S4A 智能体执行 | #5 | 498ccfb | 2026-07-09 | 272 passed | workspace_progress+agent_processes 2 model + 第4迁移(2表2索引) + OpenCodeClient真实现(dispatch_task/start_agent_serve动态端口/dispatch_pre/post_subtasks/health/shutdown 替换S3桩) + Redis超时监控(task_timeout+fakeredis) + TaskAppSvc(confirm_complete/output_confirm/output_reject/record_output/handle_timeout) + opencode callback路由 + GET tasks + webhook story4A验收；S4A rebase S4B后合并(task_app_svc.py 双方方法共存)；review P0(start_serve事务内HTTP)+3×P1(shutdown事务内HTTP/webhook retry同步HTTP/死代码)已修 |

### 下游解锁（S4A+S4B 合并后）
- **S5 日终总结**（依赖 S4B）：✅ 已解锁，可派发。需扩 state_machine 的 pause/resume/revert + audit 回退（S2 已建 status_change_log 与 forward 基础，S4B 扩了 task forward 与完成级联）；daily_records.is_confirmed 是回顾标记不级联；日终 PATCH tasks 双向改状态触发即时级联；异步写 daily.md（fileio，S5 实现）。与 S6 并行窗口 3。
- **S6 周总结**（依赖 S5）：需 S5 先合。weekly_records 表（§2.8，S6 建）+ 异步写 weekly.md。
- 并行窗口 3（{S5‖S6}）：S5 合后打开。
- **S7 子任务配置**（依赖 S1）：仍 ✅ 已解锁，与 S4/S5 无依赖，可随时并行。subtask_templates 表（§2.6）+ H5 配置。
- 注：S8（主动巡检）依赖 S5+S6；S9（轻量编辑回退）依赖 S8。
- 注：S4A 的 opencode 真实现 + agent_processes 已就位；S5 日终总结的 PATCH tasks 复用 S4B 的完成级联（双向：未完成↔已完成，回退触发重算级联）。

### 下游解锁（S3 合并后）
- S4A/S4B：✅ 已合并（见上）。

### 下游解锁（S2 合并后）
- S3 今日计划推送：✅ 已合并（见上）。

### 下游解锁（S1 合并后）
- S2 调度激活：✅ 已合并（见上）。
- S7 子任务配置：✅ 已解锁（仍可派发）。
- 并行窗口 1（{S2‖S7}）：S2 已合，S7 可独立做。
