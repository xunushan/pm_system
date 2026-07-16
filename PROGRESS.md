# 开发进度

> 本文件只维护"阶段状态 + 当前情况总结 + 遗留问题 + 下一步计划 + 参考索引"。
> 详情不抄这里：决策见 doc/07，教训见 doc/08，卡片样式见 doc/09，e2e 历史见 archive/。
> **上一阶段（schema 2.0 改造 + e2e 真测）已归档至 `archive/PROGRESS_e2e_phase.md`。**

## 一、阶段状态

- **上一阶段**：v2 修复 + schema 2.0 卡片改造 + 端到端真测。**已收官**（12 PR 合并 main：#21-#33，627 测试绿，无开放 issue）。
- **当前阶段**：e2e 收尾后的待办（见第四节遗留问题），主体功能已验证可用。
- **完成信号**：每个含卡 Story = unit/integration 绿(CI) + 契约绿(CI) + e2e 该 Story 用例真跑过(手动)。**含飞书卡片的 Story（S1-S6/S8）三者齐全，已通过。**

## 二、当前情况总结（截至 2026-07-13）

### 已完成

- **Service 9/9 Story** 全部合并 main（14 表 + 7 迁移 + 627 测试），代码层无开放 issue。
- **schema 2.0 卡片改造**：12 PR（#21-#33）。9 现有 builder + 5 新 builder 升 schema 2.0（form/checker/date_picker/column_set）；webhook 双路由（form外 action_id / form内 btn_name）+ card_registry（message_id->业务上下文 Redis 映射）。
- **方案 B 立即刷新**（PR #31）：webhook 同步在响应体返回终态卡片 `{"toast","card":{"type":"raw","data":<schema2.0>}}`，飞书 3 秒内立即更新。14 个卡片刷新回调改同步返回；耗时副作用仍异步。铁律§11（点击必刷新）落地。
- **confirm 幂等**（PR #32）：daily/weekly confirm_summary 重复点击幂等返回终态卡，不再 409。
- **S6 服务自汇总**（PR #32）：`get_weekly_stats` 补本周完成任务列表（按 `tasks.completed_at` 聚合到周）+ `push_weekly_summary_card_from_db(week, chat_id)`。pm-summary 未来只调此方法，不碰 DB、不 mock。

### e2e 真测结果（全真实，零 mock / 零手改 DB）

| Story | 状态 | 验证要点 |
|-------|------|---------|
| S1 目标规划 | ✅ | draft API -> push_overview_card -> webhook 确认 -> 4 表落库 + 删 draft |
| S2 调度激活 | ✅ | 卡片A->patch卡片B + deadline + 三级级联 + workspace 物理落盘 |
| S3 当日计划 | ✅ | 候选池 + 推卡 + 勾选确认 + executor=NULL |
| S4A 智能体执行 | ✅ | 真实 callback record_output + 验收通过/需要修改 |
| S4B 人完成 | ✅ | board 改 executor + 后置卡 + toggle 全选/全不选 |
| S5 日终总结 | ✅ | 推卡 + checker 反转 + daily.md 服务生成 + 幂等 |
| S6 周总结 | ✅ | 服务自汇总日->周 + 已阅 + weekly.md + 幂等 |
| S8 阶段衔接 | ✅ | cascade emit -> dispatcher 自动推卡 + btn_activate 激活第2阶段 |
| S7/S9 | ⏭️ | 无飞书卡片（H5 配置/看板），e2e 不测 |

**环境**：Service :8001（单进程单端口，DATABASE_URL 指向 e2e.db）+ Redis + ngrok 公网回调 + opencode serve :18800。

## 三、重要文档参考索引

| 文档 | 内容 |
|------|------|
| `doc/01_用户故事文档_v2.0.md` | 9 Story 用户视角流程 |
| `doc/02_数据模型文档_v2.0.md` | 14 表 + 视图 + 索引 + 状态机 + 级联规则 |
| `doc/03_系统架构文档_v2.0.md` | 双层架构 + Supervisor + H5 + 约束 8.1-8.21 |
| `doc/04_服务API文档_v2.0.md` | REST 接口 + webhook + drafts |
| `doc/05_Skill设计文档_v2.0.md` | 5 Skill 职责边界 |
| `doc/06_操作流程与技术动作清单_v2.0.md` | 卡片按钮路由清单（入口 B action_id/btn_name 对照） |
| `doc/07_决策文档_v1.0.md` | 历轮决策 D1-D26（含推翻项） |
| `doc/08_教训文档.md` | v2 验证教训 L1-L6 + 测试三分 + 行业标准 + 检查清单 |
| `doc/09_卡片交互样式记录.md` | UI 卡片交互样式（schema 2.0，纯 UI） |
| `doc/13_原型验证/` | 飞书卡片 + opencode 集成验证事实（V1-V9 / D27/D28） |
| `CLAUDE.md` | 架构铁律（11 条）+ 代码规范 + 开发流程 + 协作规范 |
| `service/tests/e2e/TEST_PLAN.md` | e2e 测试用例 |
| `service/app/models/__init__.py` | 代码层进度表（✅/⬜） |
| `archive/PROGRESS_e2e_phase.md` | **上一阶段（schema 2.0 改造 + e2e 真测）完整记录** |
| `archive/PROGRESS_v1_history.md` | v1 完整历史（审计用） |
| `archive/e2e_vault_snapshots/` | e2e 产出的 daily.md/weekly.md 快照（已归档） |
| `archive/e2e_workspaces/` | e2e 建的 workspace 物理目录（已归档） |
| `service/data/e2e.db.archive.*` | e2e 测试数据库快照（归档留底） |

**外部资源**：
- ngrok webhook URL：见记忆 `ngrok-webhook-url`（ngrok 重开会换 URL）
- 飞书 schema 2.0 GET 降级：见记忆 `feishu-schema2-get-degrades`（GET /im/v1/messages 查 schema 2.0 卡返回 legacy 占位，刷新态只能人工确认）
- 方案 B 实测证据：见记忆 `feishu-callback-card-data-immediate-refresh`

## 四、本阶段遗留问题

### P2（非阻塞，可后续优化）
- **[P2] S3 已确认态任务行缺阶段名**：`daily_app_svc.py` `build_daily_plan_done_card` 任务行只显示 `task.name`，丢 `phase.name`，不同阶段同名任务刷新后无法区分。dt_rows 已 JOIN Phase，加 `（{phase.name}）` 即可。
- **[观测] FeishuClient token 实例级缓存**：`refresh_*_async` 每次新建 FeishuClient 实例，token 不共享（每次多 179ms）。可改类级缓存。（方案 B 后 refresh_*_async 只用于非回调场景，影响降低）
- **[观测] Redis 容错**：`card_registry` Redis 不可用时无 try/except，建议加（与 task_timeout 一致目前无容错）
- **[P2] S4A 验收失败通知方式与设计不符**：`task_app_svc.py:648-658` 第 3 次验收不通过走 `send_text` 发纯文本飞书消息（无卡片、无 session_id）。doc/09 场景3 设计为推"需人工接手"卡片（含 workspace_path + session_id），feature-02 Story 4A 已对齐卡片设计。需把 `send_text` 改为推 doc/09 场景3 人工接手卡。
- **[P2] S2 确认后卡片仍带配置页链接**：`schedule_app_svc.py:344-369` `build_schedule_done_card` 确认后态含"调整请前往配置页"链接。但确认后 managed 已锁定不可改，链接无意义。doc/09 §S2 状态3 + feature-02 Story 2 已改为"只看初始化进度无链接"。需去掉该 markdown element（h5_url 参数保留给卡片 A，确认后态不用）。

### 未实测 / 待补
- **[未实测] S4A 真实 opencode dispatch**：e2e 测了卡片交互（btn_pass/btn_reject），但 opencode 真实执行 learning 任务时 `dispatch_task` 超时（httpcore.ReadTimeout 300s，opencode 执行卡住）。**非卡片交互问题，是 opencode 执行 learning 任务本身耗时/卡住**。需造 dev/survey 类型任务 + start_agent_serve + 等执行 + 产出回调补全。当前 S4A 验收/重试链路已通过，仅缺真实 dispatch 全程。
- **[未测] S7 子任务配置 / S9 看板**：无飞书卡片（H5），e2e 未覆盖。H5 页面骨架 + 健康检查已联通，但 H5 完整交互未测。

### 已修缺陷（归档，不再追踪）
- ~~[P1] 卡片回调后按钮长时间可点击~~ → PR #31 方案 B
- ~~[P1] confirm_summary 不幂等致重复点击报错+卡片不刷新~~ → PR #32

## 五、下一步计划与追踪

**### 优先级 1：opencode 真实 dispatch 补测（S4A 收尾）
- [ ] 造 dev/survey 类型任务（executor=agent）+ 激活阶段
- [ ] start_agent_serve（opencode serve :18800 全局单进程）
- [ ] 等真实执行完成 + 产出回调 `/api/callback/opencode/output`
- [ ] 验证 workspace_progress 落库 + 验收卡推送 + btn_pass 全程
- [ ] 追踪：当前 dispatch_task 超时根因（opencode 执行 learning 卡住 vs 超时配置）**

### 优先级 2：P2 缺陷修复
- [ ] S3 任务行补阶段名（`build_daily_plan_done_card` 加 `（{phase.name}）`）
- [ ] S4A 验收失败改推人工接手卡（`task_app_svc.py` send_text -> doc/09 场景3 卡片，含 session_id）
- [ ] S2 确认后卡去掉配置页链接（`schedule_app_svc.build_schedule_done_card` 删 h5_url markdown element）
- [ ] FeishuClient token 类级缓存
- [ ] card_registry Redis 容错

### 优先级 3：H5 交互（S7/S9）
- [ ] H5 子任务配置页（S7 subtask_templates）端到端
- [ ] H5 看板编辑 + 状态回退（S9 board API + reason 必填）

### 优先级 4：Skill 实现（交互层）
- [ ] 5 Skill（pm/pm-plan/pm-daily/pm-subtask/pm-summary）实际代码（当前仅 SKILL.md 占位，跟随 Hermes 约定）
- [ ] Skill 调 Service 推卡方法（已验证 Service 推卡全链路，Skill 只做意图识别）

### 进度日志
- 2026-07-10：复盘完成（七问 + 3 agent 证据），文档对齐落地（D25/doc/08/doc/03/CLAUDE.md）。
- 2026-07-11：飞书卡片 schema 2.0 调研，全 Story 卡片交互样式实证（doc/09）。D26 进程模型修正。
- 2026-07-13：schema 2.0 代码改造全部收官（6 PR：#25-#30）。e2e 端到端真测推进：S1-S4B 通过。发现 P1（回调后按钮可点击）。
- 2026-07-13：P1 修复（PR #31 方案 B，webhook 同步返回终态卡）。重测 S1-S3 验证立即刷新。
- 2026-07-13：S5/S6 真测通过 + confirm 幂等修复（PR #32，重复点击不再 409）+ S6 服务自汇总日->周。627 测试绿。
- 2026-07-13：S8 阶段衔接真测通过（PR #33，cascade emit -> dispatcher 自动推卡 + btn_activate 激活第2阶段）。**e2e 含飞书卡片 Story 全部真测通过，e2e 阶段收官**。e2e 测试数据清理（DB 重置空库 + Redis 清空 + vault/workspace 归档）。PROGRESS 归档至 `archive/PROGRESS_e2e_phase.md`，本文件为新一阶段起点。
