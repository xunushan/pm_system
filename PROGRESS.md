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
| S5 日终总结 | ✅已合并 | - | #6 | - | S4B | - |
| S6 周总结 | ✅已合并 | - | #8 | - | S5 | - |
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
| S5 日终总结 | #6 | a59baba | 2026-07-09 | 314 passed | 无迁移(daily_records已含is_confirmed，S3留) + state_machine补pause/resume/revert reason校验(+ReasonRequiredError 1005) + cascade新增回退级联(cascade_revert: task回退->已完成上级拉回进行中,幂等只动已完成) + fileio.write_daily_md(vault_root配置) + TaskAppSvc.patch_status异议双向(forward复用complete/revert系统填默认reason"D6/D18裁决") + DailyAppSvc.generate_summary/confirm_summary + 新建StatsAppSvc(纯查询统计) + daily/tasks/stats路由 + webhook story5_标记完成/未完成/确认日终总结(3秒返回,刷卡片+daily.md异步)；裁决D6/D18冲突(异议revert系统填reason不弹窗)；review 无P0P1(2×P2+3×P3已修: P2-1已暂停态守卫/patch_status严格待执行↔已完成双向) |
| S6 周总结 | #8 | 302dd30 | 2026-07-09 | 339 passed | weekly_records 1 model + 第5迁移(1表无索引,手动剔除autogenerate误带16个remove_index[issue#7遗留]) + WeeklyRecordRepository(get_by_week) + StatsAppSvc扩get_weekly_stats(daily_stats7天趋势/phase_health/agent_output_stats按file_type聚合/subtask_stats前置后置/supervisor_linking_status占位None[接口先行S8填]) + WeeklyAppSvc(generate_summary/confirm_summary/write_weekly_md_async) + fileio.write_weekly_md + weekly路由(替换桩为generate/confirm) + GET /stats/weekly(§3.11) + webhook story6_已阅周总结(3秒返回,weekly.md异步)；ISO周用date.fromisocalendar(周一~周日,与daily_records.week互逆一致,doc/04示例非标准ISO周)；纯回顾不改任何状态(有测试断言)；review 无P0P1(2×P2 N+1查询上限7天可忽略+1×P3风格,不阻塞) |

### 下游解锁（S6 合并后）
- **S8 主动巡检**（依赖 S5+S6）：✅ 已解锁，可派发（**关键路径：S9 依赖 S8**）。event_bus 真分发（S1-S6 一直在调 emit 桩，S8 替换为真分发，接口不变自动接上）+ scheduler 定时巡检（21:00 日终未总结提醒 / 周日 12:00 周总结推送 / deadline 临近提醒 / 10:00 未确认计划提醒）+ handlers（事件处理）。supervisor_linking_status 真逻辑由 S8 填充（S6 占位 None，S8 替换为真查询）。
- **S7 子任务配置**（依赖 S1）：仍 ✅ 已解锁，与 S8 文件不冲突可并行。subtask_templates 表（§2.6，需迁移）+ H5 配置。
- **S9 轻量编辑与回退**（依赖 S8）：需 S8 先合。board H5 编辑 + 状态回退端点 POST /board/{entity}/{id}/status（pause/resume/revert，用户显式填 reason，缺失返回 1005；state_machine 校验 S5 已实现，调用方是 S9）。
- 注：S6 已建 weekly_records（第5迁移，1表无索引）；S6 的 supervisor_linking_status 占位 None 待 S8 替换；周/日统计共用 StatsAppSvc（S5 建 S6 扩）。
- 注：alembic 遗留债 issue #7（16 索引 ORM 未声明，S1-S4B 遗留）仍未修，可并入 S9。

### 下游解锁（S5 合并后）
- **S6 周总结**（依赖 S5）：✅ 已解锁，可派发。weekly_records 表（§2.8，S6 建，需迁移）+ 异步写 weekly.md（fileio.write_weekly_md，S5 已实现 write_daily_md 可参考模式）+ 周统计复用 S5 的 StatsAppSvc（S5 已抽出纯查询核心，周总结共用）+ GET/POST /weekly/summary/generate/confirm + webhook story6_已阅周总结。与 S7 可并行（文件不冲突）。
- **S7 子任务配置**（依赖 S1）：仍 ✅ 已解锁，与 S5 无依赖，可随时并行。subtask_templates 表（§2.6，需迁移）+ H5 配置。与 S6 可并行。
- **S8 主动巡检**（依赖 S5+S6）：需 S6 先合。event_bus 真分发（S1-S5 一直在调 emit 桩，S8 替换为真分发，接口不变自动接上）+ scheduler 定时巡检（21:00 日终未总结提醒属 S8）+ handlers。
- **S9 轻量编辑与回退**（依赖 S8）：board H5 编辑 + 状态回退端点 POST /board/{entity}/{id}/status（pause/resume/revert，用户显式填 reason，缺失返回 1005；state_machine 校验 S5 已实现，调用方是 S9）。
- 注：S5 已实现 state_machine 全部分支校验（pause/resume/revert reason 必填）+ 回退级联（cascade_revert），S9 直接复用，只补 board 端点 + reason 采集表单。
- 注：S5 已为 alembic 遗留债开 issue #7（16 索引 ORM 未声明，S1-S4B 遗留，非 S5 引入，可并入 S9 修）。

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
