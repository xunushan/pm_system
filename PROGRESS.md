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
| S7 子任务配置 | ✅已合并 | - | #11 | - | S1 | - |
| S8 主动巡检 | ✅已合并 | - | #9 | - | S5,S6 | - |
| S9 轻量编辑与回退 | ✅已合并 | - | #10 | - | S8 | - |

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
| S8 主动巡检 | #9 | 20e566a | 2026-07-09 | 402 passed | 无迁移(无新表) + event_bus桩换真分发(进程内异步队列,已裁决:emit事务内queue.put_nowait不阻塞,daemon线程消费调handler,重启丢事件由巡检兜底,emit签名不变9处调用零改动) + handlers(on_phase/theme/goal_completed查下一阶段+deadline推算+推衔接卡片+Redis记时间,独立SessionLocal读DB无脏读,IO异常不崩溃) + scheduler(APScheduler5类cron巡检:scheduled_start_date/deadline临近/未确认计划10:00/未日终21:00/衔接24h未响应,Redis去重supervisor:notified,已暂停不巡检,每天1次) + linking(find_next_phase sort_order+1/compute_suggested_deadline纯计算/get_linking_status替换S6占位None) + schedules/activate端点(复用S2激活核心,triggered_by=supervisor,≤3校验,异步工作空间初始化) + webhook story8_确认激活/暂不激活/去激活/去页面调整 + main.py lifespan启停dispatcher+scheduler + conftest autouse禁用supervisor；裁决事件分发用进程内异步队列(非Redis pub/sub)；review 无P0P1(6×P2+2×P3已修:P2-1 _get_redis三处重复提redis_client.py复用[违反§11先搜后建]/P2-5 _DEFAULT_CHAT_ID私有名提constants.py/P2-2/3/4延迟import提顶/P3 _parse_iso迁times.py)；APScheduler依赖已加(pyproject) |
| S9 轻量编辑与回退 | #10 | d8f8cf1 | 2026-07-09 | 447 passed | 无迁移(无新表) + **issue#7并入修复**(12 model补16个Index声明对应migration已建索引,alembic check通过消除16个remove_index,CI加alembic check步骤防回归,Fixes#7自动关闭) + BoardAppSvc(update_fields字段编辑/阶段排序/增删任务/managed不可改 + change_status复用S5 state_machine pause/resume/revert校验+ReasonRequiredError1005,forward拒绝走activate,级联调cascade_revert_entity) + cascade新增cascade_revert_entity(通用回退入口:task委托S5既有cascade_revert[禁重写],phase/theme/goal向上回退不向下回退子task[最小回退+DB唯一真相源],幂等只动已完成上级) + state_machine扩展goal/theme pause/resume/revert(与phase同规则,doc/02 line8依据) + board路由(PUT/{entity}/{id}字段编辑+POST/{entity}/{id}/status状态变更) + DELETE /tasks/{id}物理删除+关联清理(daily_tasks/subtasks/workspace_progress手动删,FK无CASCADE) + GET /workspaces/{id}(S4A已建managed/path只读确认)；裁决issue#7并入S9(收官清债)；review 无P0P1(2×P2+1×P3已修:P2-2 _apply_phase_orders全包含校验防UNIQUE冲突+补测试/P2-1 _VALID_ENTITIES死代码删/P3 _augment_revert_result未用参数删) |
| S7 子任务配置 | #11 | 71ffa99 | 2026-07-09 | 495 passed | subtask_templates 1 model(第6迁移,§2.6:scope_type theme/phase+scope_id+type 前置/后置+name+description+status active/inactive+UNIQUE(scope_id,type,name)+2 Index[model与migration一致]) + SubtaskTemplateRepository(list/find_existing/list_active_by_scope) + ConfigAppSvc纯CRUD(list/create/update/delete + list_merged_by_task合并规则§2.18阶段优先专题同名去重[service层代码合并非SQL视图] + TemplateExistsError 3001[UNIQUE冲突] + DELETE标记inactive非物理删除可恢复幂等 + 配置不校验专题type) + subtask_templates路由(GET/POST/PUT/DELETE,prefix=/subtask-templates) + 删除config.py占位桩(被正式路由取代) + GET增task_id参数[供pm-subtask Skill,doc/04未列但§2.18合并规则入口]；alembic check通过(model Index与migration一致)；review 无P0P1(2×P2+2×P3已修:P2-2 list_merged_by_task补type校验+补测试/P2-1路由冗余elif简化/P3-2 type_命名统一/P3-1 status default[项目惯例一致skip])；**全项目收官 Story** |

## 🎯 全项目收官总览

**9/9 Story 全部合并到 main**（2026-07-09 一日内完成）：

| Story | PR | commit | 测试累计 |
|-------|-----|--------|---------|
| S1 目标规划与确认 | #1 | a6a34d3 | 90 |
| S2 调度激活 | #2 | cd8f7b8 | 137 |
| S3 今日计划推送 | #3 | 8251237 | 168 |
| S4B 人完成任务 | #4 | 0ad66b2 | 219 |
| S4A 智能体执行 | #5 | 498ccfb | 272 |
| S5 日终总结 | #6 | a59baba | 314 |
| S6 周总结 | #8 | 302dd30 | 339 |
| S8 主动巡检 | #9 | 20e566a | 402 |
| S9 轻量编辑与回退 | #10 | d8f8cf1 | 447 |
| S7 子任务配置 | #11 | 71ffa99 | 495 |

**最终状态**：
- **495 个测试全绿**（lint + alembic check + migrate 全通过）
- **14 张表**全部建成（goals/themes/phases/tasks/drafts/workspaces/daily_records/daily_tasks/workspace_progress/agent_processes/subtasks/status_change_log/weekly_records/subtask_templates）
- **6 个迁移**链完整（无多 head，alembic check 通过）
- **无遗留技术债**：issue #7（16 索引 ORM 声明）在 S9 闭环 + CI 加 alembic check 防回归
- **无 open PR / 无 open issue**
- **关键架构决策**（均在各 Story 派发前裁决）：
  - S5 异议 revert 系统填默认 reason（D6+D18 冲突裁决）
  - S8 事件总线用进程内异步队列（非 Redis pub/sub）
  - S9 issue #7 并入清债（收官清零技术债）
- **5 个 Skill 仍为 SKILL.md 占位**（CLAUDE.md §八.4）：pm/pm-plan/pm-daily/pm-subtask/pm-summary 的实际 Skill 代码需参考 Hermes 框架文档实现（交互层，非本服务层范围）
- **H5 前端仅骨架**（CLAUDE.md §八.5）：仅健康检查联通，页面设计待后续

### 下游解锁（S9 合并后 -- 收官）
- **S9 已合并**（PR #10, d8f8cf1）：收官 Story。board H5 编辑（PUT 字段/排序/增删）+ 状态回退（POST pause/resume/revert）+ DELETE 物理删除 + GET workspace managed/path。复用 S5 state_machine（扩 goal/theme）+ cascade_revert_entity（不向下回退，最小回退）。
- **issue #7 已闭环**（PR #10 Fixes #7）：12 model 补 16 个 Index 声明，`alembic check` 通过，CI 加防回归步骤。**项目无遗留技术债**。
- **剩余**：仅 **S7 子任务配置**（依赖 S1，已解锁，独立可做）。subtask_templates 表（§2.6，需迁移）+ H5 配置。
- **项目状态**：S1-S6/S8/S9 全部合并（8/9 Story），447 测试绿。仅剩 S7 未做。S7 完成即全项目收官。

### 下游解锁（S8 合并后）
- **S9 轻量编辑与状态回退**（依赖 S8）：✅ 已解锁，**最后一个 Story**。board H5 编辑（字段编辑/增删任务/阶段排序）+ 状态回退端点 `POST /board/{entity}/{id}/status`（pause/resume/revert，用户显式填 reason，缺失返回 1005；**state_machine 校验 S5 已实现全部 pause/resume/revert，调用方是 S9**，S9 直接复用，只补 board 端点 + reason 采集表单）+ 回退即时重算级联（cascade.cascade_revert S5 已实现，S9 调用）+ PUT /board/{entity}/{id}（字段编辑）+ GET /workspaces/{id}（managed/path 只读）。需迁移？S9 不建新表（用现有表 + 可能补 issue #7 的 Index 声明）。
- **S7 子任务配置**（依赖 S1）：仍 ✅ 已解锁，可与 S9 并行（文件不冲突）。subtask_templates 表（§2.6，需迁移）+ H5 配置。
- 注：S8 已实现 Supervisor 全套（event_bus 真分发 + 5 类巡检 + 衔接逻辑 + linking 真查询替换 S6 占位）；S1-S8 期间调用的 emit 桩已全部接上真分发。
- 注：alembic 遗留债 issue #7（16 索引 ORM 未声明，S1-S4B 遗留）仍未修，建议并入 S9 修（S9 触碰 model，天然时机）。

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

---

## 端到端集成验证（2026-07-10，9/9 Story 合并后）

服务层 9/9 Story 全合并后，做真实端到端验证（真实 Redis + 真实 SQLite 文件 + 真实 opencode serve 1.17.16 实测 + ngrok 公网 + 真实飞书 token + 个人 open_id）。**单测全绿不等于端到端能跑通**，本轮发现并修复 6 个问题（5 开 PR + 1 直接提交）。

### 验证通过项
- S1 规划确认 -> S2 调度激活 -> S3 今日计划 -> S4B 人完成 -> S5 日终 -> S6 周总结 -> S8 衔接激活 -> S9 看板编辑/回退：API 串联全通
- **supervisor 真实事件分发**：emit phase_completed -> daemon thread 消费 -> on_phase_completed handler -> Redis 写 `supervisor:linking:pushed:{phase_id}`（真实 Redis，非 fakeredis）
- **飞书推卡链路**：凭据有效（换到 tenant_access_token）+ ngrok 公网 + open_id，send_text/send_card 均真实收到

### 发现并修复的问题（6 项）
| PR/commit | 严重度 | 问题 | 修复 |
|-----------|--------|------|------|
| #15 (8ade308) | P1 | S3 误设 is_confirmed=True，S5 日终确认永远 409 | 删除 is_confirmed=True（model 默认 False） |
| #15 (8ade308) | P2 | 非法 push_source 返回 500（IntegrityError 穿透） | schema 改 Literal["auto","manual"] |
| #16 (b165383) | P3 | feishu app_id 空时仍调 API -> KeyError | 加 _is_configured skip |
| #17 (ffe1ddb) | P1 | webhook 未处理 url_verification 验签，飞书报"Challenge code 没有返回" | 开头加 url_verification 原样回 challenge |
| #17 (ffe1ddb) | - | DEFAULT_CHAT_ID 硬编码占位 + receive_id_type 硬编码 chat_id（推个人 open_id 失败） | config 加 feishu_default_chat_id + _receive_id_type 自动识别 ou_/on_ |
| a3ee6f4 | - | .env.example 补 FEISHU_DEFAULT_CHAT_ID 占位 | - |
| #18 (bb8a9e3) | P1 | 9 个 build_*_card 用错误结构（type:template），飞书 230099 content's type illegal | 全改飞书官方格式（config+elements+tag） |
| #19 (0a2aeff) | **P0** | opencode.py 三缺陷：无 subprocess 启动 serve + 端点全假（/task /run /health /shutdown 实测 SPA fallback）+ 协议模型错（真实是 session+message） | 重写 opencode.py 方案 B（见下） |

### P0 opencode 重写决策（方案 B：全局单进程 + 多 session）
- **决策**：doc/03 §五 设计为"每 workspace 一进程"，但真实 opencode serve 一进程天然支持多 session（POST /session 指定 directory）。采用**方案 B：全局单进程 + 多 session**，简化进程管理。
- **真实 API**（实测 opencode serve 1.17.16）：`POST /session {"directory":<绝对路径>}` 建会话 -> `POST /session/{id}/message {"parts":[{"type":"text","text":...}]}` **同步返回**结果（parts[].text + info.finish）-> `GET /session` health
- **改动**：opencode.py 重写（subprocess 全局 serve + _ensure_session 复用 + dispatch_task 同步拿结果）+ agent_processes 加 session_id（migration 130b09d5d131）+ config 加 opencode_serve_port=18800
- **铁律修复**（code-reviewer 发现）：_ensure_session 的 HTTP 移到 commit 后（原违反 §3#3 事务内禁止 IO/HTTP）+ dispatch_task 合并所有 text part + _wait_port 区分 ConnectError + main.py lifespan 加 shutdown_serve 进程清理 + 删除死配置 agent_port_range
- **doc/03 §五 是只读设计文档未改**，此决策记录在此；后续若需同步 doc，主会话评估
- 测试：539 passed（含 25+ opencode 新单测），alembic check 一致

### 遗留
- issue #20（P2，open）：build_verification_card 移除 feedback 输入框，S4A 退回流程 feedback 恒空（飞书 input 组件后续补）
- 5 Skills 仍 SKILL.md 占位（Hermes 框架，scope 外）
- H5 前端仅骨架（scope 外）

### main 最终状态
- 9/9 Story + 6 个端到端修复 PR 全合并
- 539 测试绿，7 迁移（含 session_id），14 表
- 无 open PR，仅 issue #20 open（P2 跟踪）

