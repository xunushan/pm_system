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

- [x] **代码缺口-0**：opencode.py 补 `delete_session(session_id)`（调 `DELETE /session/:sessionID`），3 次不通过时退 session（D26）。PR #25 已合。方案 B 重新排序"DB 先清 -> HTTP DELETE"消除事务2（code-reviewer P1：事务2 失败致 DB 残旧 session_id 阻断 _ensure_session 重建 -> 404）
- [x] **PR-A**：FeishuClient 适配 + 现有 9 builder 改 schema 2.0（build_verification_card/build_daily_summary_card/build_phase_linking_card 等）+ 测试改新版结构。PR #26 已合。3 主卡按 doc/09 精确（verification 含 feedback input 补 issue#20 builder 侧 / daily_summary checker / phase_linking date_picker+column_set 水平并列），6 通用卡走通用规则。两类按钮区分正确（form_submit 无 behaviors 避 V1 / form 外 behaviors callback）。code-reviewer 无 P0/P1，2 P2 非阻塞
  - ⚠️ **P2 路由缺口（归 PR-D）**：form_submit 按钮不带 task_id/daily_id（V1 要求不带 value），webhook 回调时无法直接定位 task/daily。PR-D 需补 message_id->task_id/daily_id 映射方案（send_card 返回 message_id 后存 Redis/DB，webhook 从 event.context.open_message_id 反查）
- [x] **PR-B**：补 5 个新 builder（build_plan_overview_card/build_schedule_card_a+b/build_daily_plan_card/build_task_complete_card/build_weekly_summary_card）+ 测试。PR #27 已合。6 builder 按 doc/09 精确（S4A场景4 reassign 仅智能体+name同id关联 / S6 含任务列表不含子任务 / S3 两组独立 / S2 date_picker name=dl_theme_前缀）。code-reviewer 无 P0/P1，3 P3 非阻塞
- [x] **PR-C**：补 Service 推卡入口（PlanAppSvc.push_overview_card/ScheduleAppSvc.push_schedule_card+patch_to_card_b_async/DailyAppSvc.push_daily_plan_card/WeeklyAppSvc.push_weekly_summary_card）+ story1_确认方案 + story2_下一步 webhook handler + feishu_card.py 取法修正（message_id 路径 payload["event"]["context"]["open_message_id"] 修正 FIX-1 错误取顶层 + 双路由 form外action_id/form内name + form_value 取法）。PR #28 已合。新增 app/core/card_registry.py（message_id->业务上下文 Redis 映射，P2 路由缺口落地）。code-reviewer 无 P0/P1，2 P2 非阻塞
  - ⚠️ **P2 死代码（归 PR-D 必删）**：7 个旧 action_id 分支（schedule.confirm/story3/story4A验收通过+需要修改/story4B/story5标记完成+未完成+确认日终/story8确认激活+暂不激活）在 schema 2.0 下永不触发（按钮变 form_submit 无 action_id），PR-C 保留作业务逻辑参考，**PR-D 必须删除并改为按 btn_name 路由 + form_value 业务**
  - ⚠️ **P2 card_registry Redis 容错（归 PR-D 可选）**：Redis 不可用时无 try/except，建议加（与 task_timeout 一致目前无容错）
- [x] **PR-D1**：删 7 死代码 action_id 分支 + 改 btn_name 路由（confirm_btn 按 card_registry type 分发 / btn_pass/btn_reject / btn_activate/btn_defer）+ form_value 业务（checker 对比反转 S5 / date_picker 解析 deadline S2+S8 / input feedback S4A issue#20 / reassign 互斥 S4A场景4 改 executor=agent 重新下发 D26）+ card_registry 反查。PR #29 已合。code-reviewer 2 P1（推卡映射缺口，归 PR-D2）+ 2 P2。issue#20 webhook 侧读 feedback 完成，Fixes #20
- [x] **PR-D2**：全回调 update_card 补全（12 回调刷新，build_done_card 通用终态 builder）+ delete_session 接入（trigger_reject_async manual_intervention shutdown->delete_session D26）+ 补 4 推卡映射（PR-D1 P1 回归：phase_linking handlers/scheduler + daily_summary + task_complete + post_confirm）+ reassign_to_agent 异步化 + P2 修复（refresh_schedule_done h5_url 占位符 + S4B 全选/全不选路由）。PR #30 已合。code-reviewer 无 P0/P1。**schema 2.0 代码改造收官**

合并顺序：PR-A -> PR-B -> PR-C -> PR-D（串行，依赖）。

### 端到端验证（schema 2.0 改造完成后）
- [ ] tests/e2e/TEST_PLAN.md 更新为 schema 2.0 用例（已建，需对齐 doc/09 样式）
- [ ] tests/e2e/test_infra.py 冒烟（token/推卡/回调到达/opencode 起/redis ping）
- [ ] 起真实 opencode serve（port 18800）
- [x] S1 真测通过（落库链路：draft API -> push_overview_card -> webhook 确认 -> 4 表落库 + 删 draft + executor/deadline 规划态 NULL）
- [x] S2 真测通过（S2-01 激活 3 阶段 + 三级级联 + workspace 物理落盘 git init；S2-02 第 4 个超限 409 + DB 零变化）
- [x] S3 真测通过（数据层：daily_records/daily_tasks 落库 task_id 与勾选一致 + 前置 subtask + executor=NULL）
- [x] S4A 真测通过（数据层：经真实 callback API record_output 推验收卡；btn_pass 验收通过 task 完成+级联；btn_reject 需要修改 retry_count+1+feedback。opencode 真实 dispatch 后补--retry 路径 dispatch_task 超时 httpcore.ReadTimeout 是 opencode 执行 learning 任务卡住，非卡片交互问题）
- [x] S4B 真测通过（数据层：board API 改 executor=human + PATCH 完成 + push_post_confirm_card 推后置卡；全选/全不选 toggle 方案B立即刷新；confirm_btn 后置 2 行落库（可全取消铁律§9）。**前置约束：post_confirm 要求 executor=human，e2e 跳过 Skill 需先用 board API 填 executor**）
- [x] S5 真测通过（数据层：GET /daily/summary/generate 统计 + push_daily_summary_card 推日终卡 + webhook confirm_btn daily_summary 反转 checker + is_confirmed=1 + daily.md 写入；**重复点击幂等**返回方案B绿卡，不再 409）
- [x] S6 真测通过（数据层：push_weekly_summary_card_from_db 服务自汇总日->周（按 tasks.completed_at 聚合）+ webhook story6_已阅周总结 confirm_summary 幂等 + write_weekly_md；DB 核对 4 类数据相符：本周完成 3 任务/4 阶段健康度/每日趋势/智能体产出 2 文件）
- [x] S8 真测通过（多阶段目标：1主题×2阶段×4任务经真实 API 规划+确认+激活+完成第1阶段 -> cascade emit phase_completed -> dispatcher 自动推衔接卡 -> 用户点 btn_activate 激活第2阶段。DB 核对：第2阶段 未开始->进行中 + deadline 落库 + workspace 已就绪。全链路零 mock）
- [ ] S7/S9 无飞书卡片（H5 配置/看板），e2e 不测，有飞书卡片的故事已全部真测通过

#### e2e 发现的缺陷（待修）
- ~~**[P1] 卡片回调后按钮长时间可点击**~~ ✅ 已修（PR #31 合并 de64828）。方案 B：webhook 同步在响应体返回终态卡片 `{"toast","card":{"type":"raw","data":<schema2.0>}}`，飞书立即更新（实测 S1 点击后立即变绿）。飞书官方「方式一：3秒内立即更新卡片」。耗时副作用仍异步。623 测试绿 + CI 绿 + code-reviewer 建议合并。
- ~~**[P1] confirm_summary 不幂等致重复点击报错+卡片不刷新**~~ ✅ 已修（PR #32）。daily/weekly confirm_summary 对已确认记录抛 ConflictError（409）-> 飞书收到非方案B响应 -> 卡片不刷新、按钮仍可点（违反铁律§11）。改幂等直接返回成功，重复点击也同步返回终态卡。627 测试绿（+3 回归）。
- **[P2] S3 已确认态任务行缺阶段名**：`daily_app_svc.py` build_daily_plan_done_card 任务行只显示 `task.name`，丢 `phase.name`，不同阶段同名任务刷新后无法区分。dt_rows 已 JOIN Phase，加 `（{phase.name}）` 即可。
- **[观测] FeishuClient token 实例级缓存**：`refresh_*_async` 每次新建 FeishuClient 实例，token 不共享（每次多 179ms）。可改类级缓存。（方案 B 后 refresh_*_async 只用于非回调场景，影响降低）

### 进度日志
- 2026-07-10：复盘完成（七问 + 3 agent 证据），文档对齐落地（D25/doc/08/doc/03/CLAUDE.md）。
- 2026-07-10：FIX-1+2 完成（PR #23 合并）。
- 2026-07-11：飞书卡片 schema 2.0 调研，全 Story 卡片交互样式实证（doc/09）。D26 进程模型修正 + Story4A 确认完成推卡。下一步按 PR-A~D 推进 schema 2.0 改造。
- 2026-07-13：代码缺口-0 完成（PR #25）。PR-A 完成（PR #26）。PR-B 完成（PR #27）。PR-C 完成（PR #28，webhook 双路由+message_id修正+card_registry）。PR-D1 完成（PR #29，删死代码+btn_name 路由+form_value 业务+reassign 互斥，Fixes#20）。PR-D2 完成（PR #30，全回调 update_card+delete_session+推卡映射补全+P2 修复）。**schema 2.0 代码改造全部收官（6 PR：#25-#30），下一步进 e2e 端到端真测**。
- 2026-07-13：e2e 真测推进。环境就绪（ngrok 通+Service e2e.db 干净+Redis PONG+opencode 1.17.16）。**S1 落库链路通过**（draft API->push_overview_card->webhook 确认->4 表落库+删 draft+executor/deadline 规划态 NULL，铁律§8 验证）。**S2 通过**（S2-01 激活 3 阶段+三级级联+workspace 物理落盘 git init；S2-02 第 4 个超限 409+DB 零变化，名额校验事务正确回滚）。**S3 数据层通过**（daily_records/daily_tasks task_id 与勾选一致+前置 subtask+executor=NULL）。发现 2 缺陷：[P1] 回调后按钮长时间可点击（update_card 异步致重复 confirm 风险，铁律§11）；[P2] S3 已确认态任务行缺阶段名（daily_app_svc.py:550）。实测延迟根因：webhook 119ms+update_card 1-2s+ngrok 0.2-0.7s。飞书 schema 2.0 GET 返回降级占位（刷新态只能人工确认，已记记忆）。
- 2026-07-13：**P1 修复完成（PR #31 合并 de64828）**。方案 B：webhook 同步在响应体返回终态卡片 `{"toast":{"type":"success","content":...},"card":{"type":"raw","data":<schema2.0>}}`，飞书立即更新（实测 S1 点击后立即变绿、按钮消失，无需等异步 update_card）。飞书官方「方式一：3秒内立即更新卡片」card.data 传卡片 JSON。14 个卡片刷新回调改同步返回；5 AppSvc 抽 build_*_done_card 纯函数（终态内容逐字一致）；refresh_*_async 保留供非回调场景；耗时副作用仍异步。623 测试绿+CI 绿+code-reviewer 建议合并。下一步：重测 S1/S2/S3 验证立即刷新，继续 S4A-S9。

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
