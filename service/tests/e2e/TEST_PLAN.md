# 端到端测试计划（E2E Test Plan）

> 版本：v1.0
> 日期：2026-07-10
> 适用阶段：v2 修复（FIX-1~5）完成后，S1->S9 逐项真实端到端验证。
> 性质：发布前冒烟门（不进 CI 硬门禁，依赖真实飞书/opencode/redis）。完成信号 = 每个 Story 用例真跑过。

## 一、测试三分（见 doc/08 第二节）

| 层 | 目录 | 回答 | 依赖 | 进 CI | 时机 |
|----|------|------|------|------|------|
| 集成 | tests/unit + tests/integration | Service 内链路对吗 | 全 mock | ✅ | 每 PR |
| 冒烟 | tests/e2e/test_infra.py | 外部链路通吗 | 真实 | ❌ | 部署后/起服务 |
| e2e | tests/e2e/（除 infra） | 功能对吗 | 真实 | ❌ | 发布前手动 |

**冒烟是 e2e 前置闸**：冒烟挂了 e2e 必白跑。先冒烟，绿了再跑 e2e。

## 二、全局纪律（违反即失败，不放过）

1. **禁止手改 DB**。数据准备必须经真实 API 入口（drafts -> plans/confirm -> schedules -> daily 全链路）。禁止直接 SQL UPDATE status/executor。
2. **真实点击**。飞书卡片按钮由真人点（或真实飞书回调触发），禁止脚本模拟 action_value POST。
3. **真实外部依赖**。飞书用真实 app_id/secret（.env），opencode serve 真起（port 18800），redis 用真实（非 fakeredis）。
4. **断言异步副作用**。点击后必须验证 update_card 真刷新（HTTP 返回 code=0 + 卡片内容变化），不能只看 DB。
5. **不跳 Story**。S1 -> S9 顺序执行，前一个未过不进下一个。
6. **失败如实记录**。不掩盖：失败就是失败，记录现象 + 复现步骤，不跑脚本改 DB 让它"过"。

## 三、全局前置（每次 e2e 前必做）

- [ ] Service 起在 :8001（`make dev`，指向测试库 e2e.db，隔离 pm.db）
- [ ] ngrok 隧道通（`<tunnel>.ngrok-free.dev/webhook/feishu/card` 指向 :8001）
- [ ] 飞书开放平台回调地址 = ngrok 地址（已配置，验证 challenge 能回）
- [ ] redis 起着（`brew services list` 确认 redis running）
- [ ] opencode serve 起着（port 18800，FIX-2 后真实接管任务）
- [ ] .env 含真实 FEISHU_APP_ID/SECRET/DEFAULT_CHAT_ID
- [ ] 跑冒烟 `pytest tests/e2e/test_infra.py -v` 全绿

## 四、测试数据

主数据：`vision-知识库构建.md`（项目根）。
- goal：知识库构建，4 阶段（知识获取/知识沉淀/知识库架构RAG/知识管理闭环）
- 每阶段 3 任务（理论推导/代码实现与工程化/总结+面试题库整理），全 type=learning（executor 推断=人）

**注意**：S4A 智能体执行需 dev/survey 类型任务。vision 数据全 learning 不含 agent 任务，S4A 测试需额外造 1 个 dev/survey 任务（经真实 API：drafts 写入 type=dev 的任务）。

---

## 五、冒烟用例（test_infra.py）

### TC-INFRA-01 飞书 token 能取
- 前置：.env 配好 app_id/secret
- 步骤：调 `FeishuClient._get_token()`
- 预期：返回非空 token 字符串，HTTP 200
- 通过判据：token 非空且非错误码

### TC-INFRA-02 推一张卡成功
- 前置：token 可取
- 步骤：`send_card(DEFAULT_CHAT_ID, {"config":{},"elements":[{"tag":"markdown","content":"e2e冒烟"}]})`
- 预期：飞书返回 code=0，message_id 非空，用户真实收到卡片
- 通过判据：code=0 + message_id 非空 + 人工确认收到

### TC-INFRA-03 webhook 回调能到达
- 前置：ngrok 通，飞书回调地址已配
- 步骤：飞书后台发 url_verification challenge
- 预期：Service 返回 `{"challenge": <原值>}`
- 通过判据：challenge 回显正确

### TC-INFRA-04 opencode serve 能起
- 前置：opencode CLI 已装
- 步骤：调 `OpenCodeClient.start_serve()`
- 预期：subprocess 起，port 18800 轮询 GET /session 返回 200
- 通过判据：端口可达 + session 能建

### TC-INFRA-05 redis 可 ping
- 前置：redis 服务起
- 步骤：`redis-cli ping`
- 预期：PONG
- 通过判据：PONG

---

## 六、逐 Story 用例

> 每用例 7 字段：前置 / 数据准备 / 步骤 / 卡片预期 / DB预期 / 禁止项 / 通过判据
> 通过判据 = 卡片 + DB + 日志三者齐全


### TC-S1-01 总览卡：确认方案 -> 落库 + 删 draft
- Story: S1 | 优先级: P0 | 前置: 冒烟全绿
- 数据准备: 经 `POST /api/v1/drafts` 写入规划 JSON（content 存完整规划：知识库构建 goal + 4 阶段 + 12 任务，全 learning），得到 draft_id。**禁止跳过 drafts 直调 plans/confirm**。
- 步骤:
  1. Skill/Service 触发 `push_plan_overview_card(draft_id)`（FIX-3 补 builder + FIX-4 补推卡入口），真实 send_card 推总览卡（概览 + 确认按钮，value 含 draft_id）
  2. 真实点击「确认方案」按钮 -> 飞书回调 POST /webhook/feishu/card（action_id=story1_确认方案）
- 卡片预期: update_card 重建，确认按钮置灰/消失，显示「已确认，前往 H5 调整」+ H5 链接
- DB预期: goals/themes/phases/tasks 4 表写入（draft.content 解析落库）；drafts 该条删除；goal.status=未开始
- 禁止项: 手动 INSERT 4 表；跳过 drafts 直接 plans/confirm
- 通过判据: 卡片刷新显示已确认 + 4 表有数据 + draft 表该条消失 + 无异常日志

### TC-S1-02 总览卡：draft 大数据不超 30KB（铁律 §6 验证）
- Story: S1 | 优先级: P1 | 前置: TC-S1-01
- 数据准备: 写入超大数据 draft（content JSON > 30KB，模拟满规划）
- 步骤:
  1. 推总览卡，确认按钮 value 只含 draft_id（不含完整数据）
  2. 点击确认
- 卡片预期: 正常推送（不因数据大失败）
- DB预期: 落库成功
- 禁止项: value 携带完整规划数据
- 通过判据: 卡片推送 + 确认链路全程不因数据量失败

---

### TC-S2-01 调度激活：确认调度 -> 激活 + 建 workspace
- Story: S2 | 优先级: P0 | 前置: S1 已确认（goal 落库）
- 数据准备: goal=知识库构建（S1 产出）。Service 触发 `push_schedule_card(goal_id)`（FIX-4 补推卡入口）推卡片 A（多选专题 + managed + patch 为卡片 B 填 deadline）
- 步骤:
  1. 真实点击卡片 A「下一步」-> patch 为卡片 B（填 deadline）
  2. 卡片 B 选阶段填 deadline（2026-07-15），点「确认调度」-> action_id=schedule.confirm
- 卡片预期: 卡片 A 点击后 update_card 变卡片 B；卡片 B 确认后 update_card 显示已激活 + 阶段/deadline
- DB预期: phase.status=进行中（自动锁定第1个未开始阶段）；theme.status=进行中；goal.status=进行中（即时级联）；workspaces 新建 1 条（managed=1 初始化目录）
- 禁止项: 手动 UPDATE phase status；手动建 workspace
- 通过判据: 卡片两次刷新 + phase/theme/goal 三级级联 + workspace 创建 + 无异常

### TC-S2-02 调度：名额超限 409
- Story: S2 | 优先级: P1 | 前置: 已有 3 个进行中阶段
- 数据准备: 经 TC-S2-01 造 3 个进行中阶段（真实激活，非手改）
- 步骤: 激活第 4 个 -> schedule.confirm
- 卡片预期: update_card 显示名额超限提示（或文本错误码 1004）
- DB预期: 第 4 个 phase 仍未开始（未激活）
- 禁止项: 手改 status
- 通过判据: 409/1004 + DB 未变

---

### TC-S3-01 今日计划：确认 -> daily_records 写入 + opencode 执行前置
- Story: S3 | 优先级: P0 | 前置: S2 已激活阶段
- 数据准备: 经真实激活的 phase（S2 产出）。Service 触发 `push_daily_plan_card(daily_id)`（FIX-3 补 builder + FIX-4 补入口）推今日计划卡（候选任务勾选 + 前置勾选 + 确认按钮）
- 步骤:
  1. 卡片勾选候选任务 + 前置（独立勾选，铁律 §9）
  2. 真实点击「确认今日计划」-> action_id=story3_确认今日计划
- 卡片预期: update_card 显示已确认 + 所选任务列表，按钮置灰
- DB预期: daily_records 写入（is_confirmed=True）；daily_tasks 写入选中任务；前置 subtasks 写入
- 禁止项: 手动 INSERT daily_records；手改 executor
- 通过判据: 卡片刷新 + daily_records/tasks 落库 + executor 按 type 推断（learning->human）

---

### TC-S4A-01 智能体执行：验收通过
- Story: S4A | 优先级: P0 | 前置: S3 确认（含 dev/survey 任务）+ opencode serve 起
- 数据准备: **需额外造 dev/survey 任务**（vision 全 learning 不含 agent 任务）。经 drafts 写入 type=dev 任务 -> 确认落库 -> 激活 -> 今日计划。确认计划后 opencode 真实 dispatch 主任务（FIX-2 修复后 start_agent_serve 传 task）。opencode 执行完回调 `POST /api/callback/opencode/output` 记录产出 -> 推验收卡
- 步骤:
  1. opencode 真实执行任务（产出文件）
  2. 回调记录产出 -> Service 推验收卡（build_verification_card：任务名 + 产出文件列表 + 验收通过/需要修改）
  3. 真实点击「验收通过」-> action_id=story4A_验收通过
- 卡片预期: update_card 显示已验收通过，按钮置灰/消失
- DB预期: task.status=已完成；即时级联触发（phase 进度更新）；产出文件已发飞书
- 禁止项: 手动改 task status；mock opencode
- 通过判据: opencode 真执行产出文件 + 验收卡推送 + 点击后刷新 + task 完成 + 级联

### TC-S4A-02 智能体执行：需要修改（feedback 输入框）
- Story: S4A | 优先级: P0 | 前置: TC-S4A-01
- 数据准备: 同上（另一 dev 任务）
- 步骤:
  1. opencode 执行完 -> 推验收卡
  2. 真实点击「需要修改」-> 卡片出现 feedback 输入框（FIX-5 补回 input 组件，issue #20）
  3. 填 feedback 提交 -> action_id=story4A_需要修改
- 卡片预期: 点击后 update_card 显示 feedback 输入框；提交后卡片显示已提交反馈
- DB预期: task 未完成（待执行）；feedback 记录（agent_processes/workspace_progress）；触发重试或 shutdown
- 禁止项: 跳过 feedback input 直接 reject
- 通过判据: feedback 输入框可用 + 提交后反馈记录 + 重试/shutdown 触发

### TC-S4B-01 任务完成确认：确认后置
- Story: S4B | 优先级: P0 | 前置: 有 learning 任务（人执行）完成
- 数据准备: 经真实入口造 learning 任务 -> 标记完成（真实 PATCH，即时级联）。Service 触发 `push_task_complete_card(task_id)`（FIX-3 补 build_task_complete_card + FIX-4 补入口）推任务完成确认卡（后置清单勾选 + 确认后置/不需要后置按钮）
- 步骤:
  1. 卡片勾选后置子任务（默认全选，可取消，铁律 §9 后置可全取消）
  2. 真实点击「确认后置」-> action_id=story4B_确认后置
- 卡片预期: update_card 显示已确认后置，按钮置灰
- DB预期: 后置 subtasks 写入（selected 状态）；异步触发 opencode 执行后置
- 禁止项: 手动 INSERT subtasks
- 通过判据: 卡片刷新 + subtasks 落库 + opencode 异步执行后置

### TC-S4B-02 任务完成确认：不需要后置
- Story: S4B | 优先级: P1 | 前置: TC-S4B-01
- 数据准备: 承接 TC-S4B-01（同一已完成任务，换一张任务完成确认卡或复用）
- 步骤: 真实点击「不需要后置」-> action_id=story4B_不需要后置
- 卡片预期: update_card 显示已确认（无后置）
- DB预期: task 仍已完成（铁律 §9 后置脱钩，不做后置不影响完成）
- 禁止项: 因不选后置把 task 拉回未完成
- 通过判据: task 保持已完成 + 无后置执行

---

### TC-S5-01 日终总结：标记完成 -> 卡片按钮反转（FIX-1 验证）
- Story: S5 | 优先级: P0 | 前置: S3 确认计划，有当日任务
- 数据准备: 经真实入口造 daily_records + 当日任务。Service 触发 `push_daily_summary_card(daily_id)`（FIX-4 补入口）推日终总结卡（任务列表 + 状态切换按钮 + 确认按钮，**按钮 per-item 挨任务，FIX-5 样式**）
- 步骤:
  1. 真实点击某未完成任务的「标记完成」-> action_id=story5_标记完成
  2. **验证 message_id 传递**（FIX-1：build_daily_summary_card 的 button value 含 message_id；回调读取后 update_card）
- 卡片预期: update_card 重建，该任务按钮反转（标记完成 -> 标记未完成），任务状态显示✅
- DB预期: task.status=已完成；即时级联触发（phase/theme/goal 进度）
- 禁止项: 手改 task status；mock update_card 不断言
- 通过判据: **message_id 非空**（FIX-1 核心验证）+ 卡片真刷新按钮反转 + task 完成 + 级联 + update_card HTTP code=0

### TC-S5-02 日终总结：标记未完成（回退）
- Story: S5 | 优先级: P0 | 前置: TC-S5-01（有已完成任务）
- 数据准备: 承接 TC-S5-01（TC-S5-01 标记完成后的日终总结卡，存在已完成任务可回退）
- 步骤: 真实点击已完成任务的「标记未完成」-> action_id=story5_标记未完成
- 卡片预期: update_card 按钮反转回（标记未完成 -> 标记完成），状态❌
- DB预期: task.status=待执行；级联回退（可能把 phase 拉回进行中）
- 禁止项: 手改 status
- 通过判据: 卡片刷新反转 + task 回退 + 级联

### TC-S5-03 日终总结：确认日终总结
- Story: S5 | 优先级: P0 | 前置: TC-S5-01/02
- 数据准备: 承接 TC-S5-01/02（当日 daily_records 已存在，任务状态已调整完毕）
- 步骤: 真实点击「确认日终总结」-> action_id=story5_确认日终总结
- 卡片预期: update_card 显示已确认，按钮置灰/消失
- DB预期: daily_records.is_confirmed=True；daily.md 快照写入（Obsidian）
- 禁止项: 手改 is_confirmed
- 通过判据: 卡片刷新 + is_confirmed + daily.md 生成

---

### TC-S6-01 周总结：已阅
- Story: S6 | 优先级: P0 | 前置: 有本周 daily_records（S5 产出）
- 数据准备: 经真实 S5 产出本周日终记录。scheduler 周日 12:00 定时触发（或手动触发 `WeeklyAppSvc.generate_summary`）-> 推周总结卡（FIX-3 补 build_weekly_summary_card + FIX-4 补推卡入口：每日回顾/阶段健康/产出/下周建议 + 已阅按钮）
- 步骤: 真实点击「已阅」-> action_id=story6_已阅周总结
- 卡片预期: update_card 显示已阅，按钮置灰/消失
- DB预期: weekly_records.is_confirmed=True；weekly.md 快照写入
- 禁止项: 手改 weekly_records；混淆 build_theme_completed（那是 S8）
- 通过判据: 周总结卡推送（含每日回顾+健康度，非主题完成卡）+ 点击刷新 + weekly_records + weekly.md

---

### TC-S8-01 阶段衔接：确认激活下阶段
- Story: S8 | 优先级: P0 | 前置: 某阶段所有任务完成（经真实完成，非手改）
- 数据准备: 经真实 PATCH 完成 phase 内所有任务 -> 即时级联触发 phase_completed 事件 -> supervisor handler 推衔接卡（build_phase_linking_card：下一阶段 + deadline + 确认/暂不激活）
- 步骤: 真实点击「确认激活」-> action_id=story8_确认激活
- 卡片预期: update_card 显示已激活下阶段
- DB预期: 下个 phase.status=进行中；workspace 已就绪
- 禁止项: 手改 phase status 触发事件
- 通过判据: 事件真实触发 + 衔接卡推送 + 点击刷新 + 下阶段激活

### TC-S8-02 阶段衔接：暂不激活
- Story: S8 | 优先级: P1 | 前置: TC-S8-01
- 数据准备: 承接 TC-S8-01（另一阶段完成的衔接卡，下阶段未开始可暂不激活）
- 步骤: 真实点击「暂不激活」-> action_id=story8_暂不激活
- 卡片预期: update_card 显示已暂缓
- DB预期: 下个 phase 仍未开始
- 禁止项: -
- 通过判据: 卡片刷新 + phase 未变

---

### TC-S9-01 看板：H5 编辑（无卡，board API）
- Story: S9 | 优先级: P0 | 前置: S2 已激活实体
- 数据准备: 经真实激活的实体（S2 产出）
- 步骤:
  1. H5 页面调 `PATCH /api/v1/board/tasks/{id}` 改任务字段
  2. H5 页面调 `PATCH /api/v1/board/status` 改状态（回退，reason 必填）
  3. H5 页面调 `DELETE /api/v1/board/tasks/{id}` 物理删除
- 卡片预期: 无卡（S9 全走 H5）
- DB预期: 任务字段更新；status_change_log 写入（含 reason）；任务物理删除
- 禁止项: 手改 DB；回退不填 reason
- 通过判据: board API 三个操作落库 + status_change_log + 删除生效

### TC-S9-02 看板：回退 reason 必填（铁律 §7）
- Story: S9 | 优先级: P0 | 前置: TC-S9-01
- 数据准备: 承接 TC-S9-01（已激活实体存在，可对其回退）
- 步骤: 回退不带 reason 调 board/status
- 卡片预期: 无卡
- DB预期: 拒绝（错误码 1005），status_change_log 无新增
- 禁止项: -
- 通过判据: 1005 + 状态未变

---

## 七、完成判据汇总

| Story | 用例数 | 完成判据 |
|-------|--------|---------|
| S1 | 2 | 总览卡推送 + draft 真写入 + 确认落库删 draft |
| S2 | 2 | 调度卡 patch + 激活级联 + workspace |
| S3 | 1 | 今日计划卡 + daily_records + executor 推断 |
| S4A | 2 | opencode 真执行 + 验收卡两场景（通过/修改） |
| S4B | 2 | 任务完成卡 + 后置两场景（确认/不需要） |
| S5 | 3 | 日终卡 + message_id 传递（FIX-1）+ 按钮反转 + 确认 |
| S6 | 1 | 周总结卡（非主题卡）+ 已阅 + weekly.md |
| S8 | 2 | 事件触发衔接卡 + 两场景 |
| S9 | 2 | board 三操作 + 回退 reason 必填 |

**全部用例通过 = v2 阶段完成 = Service 真正可用。**

## 八、关联

- 教训与测试三分：doc/08
- 卡片归属决策：doc/07 D25
- v1 失败历史：archive/PROGRESS_v1_history.md
- 进度追踪：PROGRESS.md 第三节
