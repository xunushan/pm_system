# 目标管理系统 — Skill 设计文档

> 版本：v2.0
> 日期：2026-07-08
> 基于：目标管理系统完整方案 v2.0 + 流程优化方案（五轮 review 后）
> 说明：本文档只定义 Skill 逻辑，不讨论实现细节
> 变更（v2.0，五轮 review 后最终版）：
> 1. **Skill 5 个原子能力** — pm/pm-plan/pm-daily/pm-subtask/pm-summary，去剧本化
> 2. **pm 主路由纯路由 + 预填链接** — pm 不直接调 Service；生成类路由到子 Skill，配置类生成预填 H5 链接
> 3. **pm-plan 收敛** — 只沟通+产出规划，逐专题生成追加到 drafts，总览卡片触发写库
> 4. **pm-daily 增加 executor 推断 + 前置整体生成** — 按专题 type 推断 executor，前置按今日整体生成（不按单个任务）
> 5. **pm-subtask 承担前置（今日整体）+ 后置（单个任务）** — type 参数区分，Service 不调 LLM
> 6. **配置类操作不建 Skill** — 走 H5 页面 CRUD，pm 配置类指令生成预填链接
> 7. **Story 编号更新** — Story 1（原0+1）、Story 8（原9）、Story 9（原10）

---

# 一、Skill 判定原则与清单

## 1.1 Skill 判定标准

> **唯一标准：能力的核心逻辑是否需要 LLM 推理/生成/理解。**
> - 需要 LLM → Skill（智能体执行，加载 Skill 描述）
> - 纯确定性逻辑（CRUD、查询、排序、状态机、级联计算、定时巡检、HTTP 调用）→ Service 代码

> **数量控制**：共 5 个 Skill，每个仅承担"LLM 不可替代"的核心逻辑，避免智能体上下文加载过多 Skill 描述。

## 1.2 Skill 清单（共 5 个）

| Skill 名称 | 触发方式 | 功能范围（仅 LLM 部分） | 调用 Service API |
|-----------|---------|----------|-----------------|
| **pm** | Hermes Agent 识别 `/pm` 前缀 | 纯路由 + 意图识别 + 配置类生成预填 H5 链接 | 无（不直接调 Service） |
| **pm-plan** | 由 `pm` 路由（关键词：规划/创建目标） | 全程聊天沟通+逐专题生成规划+追加到 drafts+总览卡片触发写库 | `/api/v1/drafts/*` |
| **pm-daily** | 由 `pm` 路由（关键词：今日计划）或 8:30 定时触发 | 今日计划决策（昨日完成+进度+deadline）+ executor 推断 + 调 pm-subtask 生成前置（整体） | `/api/v1/daily/plans/pool`, `/api/v1/daily/confirm` |
| **pm-subtask** | 由 `pm-daily` 调用（前置）或 `pm` 路由（/pm 完成）调用（后置） | 前置（今日整体）+ 后置（单个任务）子任务生成，type 参数区分 | `/api/v1/subtask-templates`, `/api/v1/workspaces/{id}/progress`, `/api/v1/tasks/{id}/complete`, `/api/v1/tasks/{id}/post-confirm` |
| **pm-summary** | 由 `pm` 路由（关键词：今日总结/本周总结）或定时触发 | 日终/周总结文案 + 建议（下周建议参考 Supervisor 衔接状态） | `/api/v1/stats/*`, `/api/v1/daily/summary/confirm`, `/api/v1/weekly/summary/confirm` |

## 1.3 下沉为 Service 代码的能力（非 Skill）

| 能力 | 归属 | 理由 |
|------|------|------|
| 调度候选查询、阶段自动锁定（sort_order 最小未开始）、卡片 patch | `ScheduleAppSvc` | 查询+模板填充 |
| 调度激活、工作空间初始化（managed 分支）、即时级联、状态机 | `ScheduleAppSvc` | 事务+IO |
| 今日计划任务池筛选（已激活阶段+排除已暂停） | `DailyAppSvc` | 纯查询过滤 |
| 日终/周总结的统计查询 | `StatsAppSvc` | 纯查询统计 |
| 任务定位、完成标记、即时级联 | `TaskAppSvc` | 状态机+级联 |
| 智能体任务下发（HTTP POST OpenCode）、回调解析、验收卡片、文件发送、超时告警、重试路由 | `AgentAppSvc` | HTTP+解析，无 LLM |
| 模板配置 CRUD | `ConfigAppSvc` | 纯 CRUD |
| 项目空间关联设置 | `WorkspaceAppSvc` | 字段填写 CRUD |
| 主动巡检（deadline/未总结/衔接未响应/scheduled_start_date 提醒）+ 阶段衔接建议 | `Supervisor` 组件 | 定时查询+条件判断 |
| 轻量编辑（H5 页面落库、状态校验、级联） | `BoardAppSvc` | CRUD+状态机 |

> **卡顿监测暂不做**（原设计的任务卡顿巡检不实现）。

---

# 二、Skill 设计原则

1. **Skill 是交互层的 HTTP 客户端**：不直接操作数据库，通过调用 Service REST API 完成数据操作。
2. **Skill 内部封装 CardKit 代码**：负责飞书卡片创建、更新、拼装，数据来源是 Service API 返回。
3. **Skill 只进讨论态**：Skill 执行过程中不触发数据库写事务；只有用户点击卡片按钮或 H5 页面提交后，Service 才执行事务。
4. **Skill 负责 LLM 提示工程**：将用户自然语言转化为结构化 API 请求参数，将 API 返回数据转化为用户友好回复。
5. **能力与编排分离**：Skill 暴露原子能力 + 输入输出契约，编排交给上层调度器。同一能力可被用户指令、定时任务、巡检器、回调四类入口复用。
6. **pm 主 Skill 纯路由**：pm 不直接调 Service。生成类路由到子 Skill（子 Skill 调 Service）；配置类生成预填 H5 链接。
7. **Service 不调 LLM**：前置/后置等需 LLM 生成的内容，必须由 Skill 调用，Service 不主动调 LLM。

---

# 三、pm 主 Skill（纯路由 + 预填链接）

## 3.1 定位

`pm` 是系统的**主路由 Skill**，由 Hermes Agent 框架识别 `/pm` 前缀后唯一路由。它本身不执行业务逻辑，也不直接调 Service。两类处理：
- **生成类指令**：解析后续内容，通过关键词匹配调用 `skill_view()` 路由到对应子 Skill（子 Skill 调 Service）。
- **配置类指令**：LLM 提取结构化参数 → 生成预填 H5 链接（不调 Service），引导用户在 H5 页面确认提交。

## 3.2 触发条件

| 触发条件 | 匹配模式 |
|----------|----------|
| 用户消息以 `/pm` 开头 | 前缀匹配 `/pm` |

## 3.3 二级路由规则

| 用户输入模式 | 关键词 | 路由到 |
|-------------|--------|---------------|
| `/pm 帮我规划...` / `/pm 规划...` / `/pm 创建目标...` | 规划、创建目标 | `pm-plan` |
| `/pm 今日计划` | 今日计划 | `pm-daily` |
| `/pm 完成 [任务]` | 完成 | `pm-subtask`（type=后置） |
| `/pm 确认完成 [任务]` | 确认完成 | **直接调 `POST /tasks/{id}/confirm-complete`**（4A 人工确认，无后置生成，不进 pm-subtask） |
| `/pm 今日总结` | 今日总结 | `pm-summary` |
| `/pm 本周总结` | 本周总结 | `pm-summary` |
| `/pm 配置子任务` / `/pm 关联项目空间` | 配置、关联项目空间 | **不分派子 Skill**（pm LLM 提取参数 → 生成预填 H5 链接） |

> **注**：`/pm 确认完成` 是 4A 场景（3 次重试不通过后用户介入处理），pm 识别后直接调 `tasks/{id}/confirm-complete`（无后置生成，不进 pm-subtask）。这与 `/pm 完成`（4B，进 pm-subtask 生成后置）区分。

## 3.4 配置类预填链接机制

pm 收到配置类指令 → LLM 提取参数 → 拼成 URL 查询参数 → 生成 H5 链接 → 返回给用户。

```
/pm 关联项目空间 深度学习基础 /Users/me/dl_notes

pm LLM 提取：{ action: "link-workspace", theme: "深度学习基础", path: "/Users/me/dl_notes", managed: 0 }
生成链接：https://pm.example.com/page?action=link-workspace&theme=深度学习基础&path=...&managed=0

用户点击链接 → H5 页面读取 URL 参数预填表单 → 用户确认提交 → 页面调 Service
```

## 3.5 执行逻辑

```
Step 1: 接收用户消息，提取 /pm 后内容
Step 2: 关键词匹配
  ├── 生成类关键词（规划/今日计划/完成/总结/确认完成）→ 路由到对应子 Skill 或直接调 confirm-complete
  └── 配置类关键词（配置/关联项目空间）→ LLM 提取参数 → 生成预填 H5 链接 → 返回链接
Step 3: 子 Skill 执行（仅生成类）
```

## 3.6 边界情况

| 场景 | 处理 |
|------|------|
| 关键词未匹配 | 提示可用指令 |
| 多个匹配 | 最长匹配优先，否则歧义提示 |
| /pm 后无内容 | 提示补充指令 |

## 3.7 与 Service 的交互

`pm` 主 Skill **不直接调用任何 Service API**（生成类由子 Skill 调，配置类只生成链接）。职责仅限：
- 解析 /pm 前缀
- 关键词匹配 + 路由
- 配置类 LLM 提取参数 + 生成预填链接
- `/pm 确认完成` 直接调 `tasks/{id}/confirm-complete`（唯一例外，因为是轻量确认不生成内容）

---

# 四、pm-plan Skill（规划生成 + 写 drafts）

## 4.1 触发条件

由 `pm` 路由，关键词：规划、创建目标。

## 4.2 能力契约

**输入**：用户原始消息（如"帮我规划具身智能算法岗面试准备，3个月"）。

**LLM 核心逻辑**：
- 提问引导：专题构成 → 目标时间范围 → scheduled_start_date → 逐专题阶段任务
- 从一句话生成目标/专题/阶段/任务四层结构
- 逐专题生成，每专题确认后进下一个

**输出**：写入 drafts（逐专题追加）+ 总览卡片（概览 + 确认按钮，按钮 action_value 只含 draft_id）。

## 4.3 执行逻辑

```
pm-plan 提问引导策略（配置在 Skill 里）：
  Step 1: 意图识别 → 提取目标名称、时间范围
  Step 2: 提问专题构成 → LLM 生成候选专题 → 用户确认/调整
  Step 3: 提问目标时间范围（粗略，如"3个月，7月到9月"）→ 用户确认
  Step 4: 提问 scheduled_start_date（计划开始日）→ 用户确认
  Step 5: 逐专题沟通阶段和任务：
    5.1: LLM 生成该专题的阶段列表 → 用户确认/调整
    5.2: LLM 生成每阶段任务 → 用户确认/调整
    5.3: 该专题确认 → 追加到 drafts（调 PUT /drafts/{id}）
    5.4: 进入下一专题，重复 5.1-5.3
  Step 6: 所有专题讨论完 → 生成总览卡片（只展示概览：专题数/阶段数/任务数）+ 确认按钮（action_value=draft_id）

确认（不由 Skill 执行）：
  Step 7: 用户点击"确认方案" → 回调只传 draft_id → Gateway 硬编码路由 → POST /plans/confirm
    → Service 用 draft_id 读 drafts → 写正式表 → 删 drafts → 返回 H5 链接
```

## 4.4 设计要点

- **pm-plan 职责收敛**：只沟通+产出规划，产出后退场，不参与后续调整（调整走 H5 页面）。
- **逐专题生成追加到 drafts**：每专题确认后调 PUT /drafts/{id} 追加内容，避免一次生成大量内容。
- **总览卡片只展示概览**：不展示全部细节（细节在 H5 页面），规避飞书回调数据量限制。
- **确认按钮只传 draft_id**：规划数据可达几十 KB，不经过回调（存 drafts，回调只传 draft_id）。
- **规划态产出**：目标（名称+时间范围+scheduled_start_date+描述）、专题（名称+类型，无 sort_order/time_range）、阶段（名称+sort_order，无 deadline）、任务（名称，无 executor）。

## 4.5 调用 Service API

| 步骤 | API | 方法 | 说明 |
|------|-----|------|------|
| 创建 drafts | `/api/v1/drafts` | POST | 首次创建草稿 |
| 追加更新 drafts | `/api/v1/drafts/{draftId}` | PUT | 逐专题追加（乐观锁） |
| 确认方案 | `/api/v1/plans/confirm` | POST | 用 draft_id 读 drafts 写正式表（Gateway 硬编码路由） |

---

# 五、pm-daily Skill（今日计划决策 + executor 推断）

## 5.1 触发条件

| 触发条件 | 说明 |
|----------|------|
| 由 `pm` 路由（`/pm 今日计划`） | 用户主动触发 |
| 定时 8:30 | 系统定时触发 |
| 巡检触发（10:00 未确认计划） | Supervisor 提醒后用户触发 |

## 5.2 能力契约

**输入**：Service 预查询的"今日任务池"（含昨日完成、当前进行中阶段、各任务 deadline、任务依赖、theme_type）。

**LLM 核心逻辑**：
- 综合昨日完成+进度+deadline+依赖，决策今日候选任务（5-8 个）
- 按专题 type 推断每个候选任务的 executor
- 调 pm-subtask 生成"今日整体前置"（不按单个任务）

**输出**：今日计划卡片（候选任务勾选 + 前置勾选，两组独立 + 确认按钮）。

## 5.3 执行逻辑

```
Step 1: 任务池预查询（Service 代码，非 LLM）
  → GET /api/v1/daily/plans/pool?user_id=&date=
  → Service 过滤：已激活阶段（activated_at 有值）+ 待执行任务 + 排除已暂停
  → 返回结构化任务池（含昨日完成、deadline、theme_type）

Step 2: 今日计划决策（LLM）
  → 输入：任务池 + 昨日完成情况 + 阶段进度
  → LLM 决策：今天做哪几个、顺序、数量（5-8 个候选）

Step 3: executor 推断（LLM/规则）
  → 按所属专题 type 推断：
    learning/research/source → human
    dev/survey → agent
  → 卡片只读展示 executor，要改走 H5 页面

Step 4: 前置子任务生成（调 pm-subtask 能力，type=前置，今日整体）
  → 输入：今日候选任务（executor=人 的）+ 模板
  → pm-subtask 生成"今日整体前置"（不按单个任务）
  → 详见第六章

Step 5: 生成可交互卡片
  → CardKit：候选任务勾选框（每行：任务名（阶段名(deadline)）[executor]）+ 前置勾选框（两组独立）
  → 按钮："确认今日计划"
  → 确认前数据只在卡片（无 drafts）

调整（可选）：
  Step 6: 用户勾选任务（3-5 个）+ 勾选前置（可取消，与任务解耦）
    → 两组独立勾选，取消任务不影响前置

确认（不由 Skill 执行）：
  Step 7: 用户点击"确认今日计划" → Gateway 硬编码路由 → POST /daily/confirm
    → 写 daily_records/daily_tasks/subtasks（前置）→ 异步执行前置 + 启动智能体
```

## 5.4 executor 推断规则（配置在 Skill 里）

| 专题 type | executor 推断 | 理由 |
|-----------|----------|------|
| learning | human | 学习推导类，人为主 |
| research | human | 调研阅读类，人为主 |
| source | human | 资料整理类，人为主 |
| dev | agent | 代码开发类，智能体为主 |
| survey | agent | 选型对比类，智能体可代劳 |

> 推断结果卡片只读展示。用户要改走 H5 页面（Story 9 改 executor）。

## 5.5 调用 Service API

| 步骤 | API | 方法 | 说明 |
|------|-----|------|------|
| 任务池预查询 | `/api/v1/daily/plans/pool` | GET | Service 过滤（只读） |
| 确认今日计划 | `/api/v1/daily/confirm` | POST | 确认（Gateway 硬编码路由） |

---

# 六、pm-subtask Skill（前置整体 + 后置单个生成）

## 6.1 触发条件

| 触发条件 | type 参数 | 说明 |
|----------|----------|------|
| 被 pm-daily 调用 | 前置 | 今日计划决策后生成"今日整体前置" |
| 由 `pm` 路由（`/pm 完成 [任务]`） | 后置 | 人完成任务时生成后置 |

## 6.2 能力契约

**输入（前置）**：今日候选任务（executor=人）+ 模板列表（Service 合并阶段级+专题级）。
**输入（后置）**：任务上下文 + 模板列表 + 工作空间文件快照。

**LLM 核心逻辑**：
- 前置：模板 + 今日任务上下文 → 生成"今日整体前置"清单（不按单个任务）
- 后置：模板 + 任务上下文 + 文件快照 → 生成单个任务的后置清单

**输出**：
- 前置：返回给 pm-daily，合并入今日计划卡片
- 后置：生成后置勾选卡片（默认全选，可取消，可全取消）

## 6.3 执行逻辑

### 前置子任务生成（type=前置，被 pm-daily 调用）

```
Step 1: 获取模板 → GET /api/v1/subtask-templates?type=前置
  → Service 按合并规则返回（阶段优先于专题，同名去重）
Step 2: 组装 LLM Prompt = 模板 + 今日候选任务（executor=人）上下文
Step 3: LLM 生成"今日整体前置"清单（填充变量、细化描述，不按单个任务）
Step 4: 返回给 pm-daily，合并入今日计划卡片（前置勾选框，与任务独立）
```

> **前置只对人执行任务**：pm-daily 推断 executor 后，只对 executor=人 的任务调 pm-subtask 生成前置。智能体任务不生成前置。
> **前置与任务解耦**：前置按今日整体生成，不按单个任务，两组独立勾选，取消任务不影响前置。

### 后置子任务生成（type=后置，/pm 完成 时触发）

```
Step 1: 获取任务详情 → GET /api/v1/tasks/{taskId}
Step 2: 获取模板 → GET /api/v1/subtask-templates?type=后置
Step 3: 获取工作空间文件快照 → GET /api/v1/workspaces/{workspaceId}/progress
  → LLM 判断后置需合并/更新/新建已有文件
Step 4: 组装 Prompt → LLM 生成后置清单
Step 5: 调 Service 标记任务完成（POST /tasks/{id}/complete）→ 即时级联（任务此时已完成，脱钩）
Step 6: 生成后置勾选卡片（默认全选，可取消，可全取消）+ 确认后置按钮 + 不需要后置按钮

后置确认（不由 Skill 执行）：
  Step 7: 用户勾选 → 点击"确认后置"/"不需要后置" → Gateway 路由 → POST /tasks/{id}/post-confirm
    → 写入勾选的后置（全取消则不写）→ 异步执行后置（opencode run）
```

> **后置只对人执行任务**：智能体任务不生成后置（4A 不进 pm-subtask）。
> **后置和完成脱钩**：Step 5 标记完成（即时级联），后置是可选收尾（Step 6-7），用户可全取消，任务仍是已完成。

## 6.4 调用 Service API

| 步骤 | API | 方法 | 说明 |
|------|-----|------|------|
| 任务详情 | `/api/v1/tasks/{taskId}` | GET | 获取任务详情（后置场景） |
| 模板查询 | `/api/v1/subtask-templates` | GET | 获取模板（阶段优先于专题合并） |
| 工作空间进展 | `/api/v1/workspaces/{workspaceId}/progress` | GET | 获取文件快照（后置场景） |
| 标记完成 | `/api/v1/tasks/{taskId}/complete` | POST | 标记完成+即时级联（后置场景，脱钩） |
| 后置确认 | `/api/v1/tasks/{taskId}/post-confirm` | POST | 确认后置（Gateway 硬编码路由，可全取消） |

---

# 七、pm-summary Skill（日终/周总结文案 + 建议）

## 7.1 触发条件

| 触发条件 | 子功能 |
|----------|--------|
| `/pm 今日总结` 或 21:00 定时提醒 | 日终总结 |
| 周日 12:00 定时 | 周总结 |

## 7.2 能力契约

**输入**：Service 预查询的统计数据（日：今日完成/未完成/阶段健康度；周：本周每日完成趋势/阶段完成率/产出清单/Supervisor 衔接状态）。

**LLM 核心逻辑**：
- 统计数据 → 生成用户友好的总结文案 + 个性化建议
- 周总结：下周建议参考 Supervisor 衔接状态，保持一致

**输出**：总结文案卡片 + 按钮。

## 7.3 执行逻辑

### 日终总结

```
Step 1: 统计预查询（Service 代码）→ GET /api/v1/daily/summary/generate
  → 返回：今日完成/未完成/阶段健康度（状态已即时级联更新）
Step 2: 文案与建议生成（LLM）→ 输入统计数据 → 生成文案 + 建议
Step 3: 生成总结卡片：
  今日任务列表（每项带状态切换按钮：未完成显示[标记完成]，已完成显示[标记未完成]）
  + 步骤进展 + 建议 + 确认日终总结按钮

异议修正（可选，双向，卡片直接改）：
  Step 4: 用户点状态切换按钮 → Service PATCH /tasks/{id}（即时级联 + 重新统计 + 刷新卡片，按钮文案反转）

确认（不由 Skill 执行）：
  Step 5: 用户点击"确认日终总结" → Gateway 路由 → POST /daily/summary/confirm
    → 仅写 daily.md 快照 + 标记 is_confirmed（不级联）
```

> **日终总结纯回顾**：不执行级联（级联已即时化）。异议走卡片直接改状态（按钮动作形态，双向，直接改不弹确认）。

### 周总结

```
Step 1: 统计预查询 → GET /api/v1/weekly/summary/generate（含 supervisor_linking_status）
Step 2: 文案与下周建议生成（LLM）→ 参考 Supervisor 衔接状态保持一致
Step 3: 生成总结卡片（已阅按钮）
Step 4: 异议 → 重新预查询（不修改底层状态）→ 刷新卡片
Step 5: 用户点击"已阅" → Gateway 路由 → POST /weekly/summary/confirm → 写 weekly.md
```

> **周总结纯回顾**：不修改任何状态。异议不修改底层状态，修正回当天日终或 H5 页面。

## 7.4 调用 Service API

| 步骤 | API | 方法 | 说明 |
|------|-----|------|------|
| 日统计 | `/api/v1/daily/summary/generate` | GET | 生成日终统计数据（只读） |
| 周统计 | `/api/v1/weekly/summary/generate` | GET | 生成周统计数据（只读，含衔接状态） |
| 任务修正 | `/api/v1/tasks/{taskId}` | PATCH | 异议修正单条任务状态（即时级联） |
| 确认日终 | `/api/v1/daily/summary/confirm` | POST | 确认（Gateway 硬编码路由） |
| 确认周总结 | `/api/v1/weekly/summary/confirm` | POST | 确认（Gateway 硬编码路由） |

---

# 八、Skill 与 Service 代码能力边界

## 8.1 能力归属对照

| 业务动作 | LLM? | 归属 | 入口 |
|----------|------|------|------|
| 意图识别 + 路由 | ✅ | Skill `pm` | 用户指令 |
| 规划生成 | ✅ | Skill `pm-plan` | 用户指令 |
| 全程聊天沟通（逐专题确认） | ✅ | Skill `pm-plan` | 用户指令 |
| 今日计划决策 | ✅ | Skill `pm-daily` | 用户指令 / 定时 / 巡检 |
| executor 推断 | ✅（规则） | Skill `pm-daily` | 被 pm-daily 调用 |
| 前置生成（今日整体） | ✅ | Skill `pm-subtask` | 被 pm-daily 调用 |
| 后置生成（单个任务） | ✅ | Skill `pm-subtask` | /pm 完成 |
| 日/周总结文案+建议 | ✅ | Skill `pm-summary` | 用户指令 / 定时 |
| 日/周统计查询 | ❌ | Service `StatsAppSvc` | 被 pm-summary 调用 |
| 调度激活 + 工作空间初始化 + 阶段自动锁定 | ❌ | Service `ScheduleAppSvc` | 确认调度回调 |
| 任务完成 + 即时级联 | ❌ | Service `TaskAppSvc` | pm-subtask 内调 / 回调 |
| 智能体下发/回调/验收卡片/文件发送 | ❌ | Service `AgentAppSvc` | 事件 |
| 模板配置 CRUD | ❌ | Service `ConfigAppSvc` | H5 页面 |
| 项目空间关联设置 | ❌ | Service `WorkspaceAppSvc` | Story 2 卡片 A / H5 |
| 主动巡检 + 阶段衔接建议 | ❌ | Service `Supervisor` | 定时 / 事件 |
| 轻量编辑落库 + 状态校验 | ❌ | Service `BoardAppSvc` | H5 页面 |

## 8.2 编排复用原则

同一能力被多入口复用：
- `pm-daily`（今日计划决策）：用户 `/pm 今日计划`、8:30 定时、10:00 巡检提醒后，均调同一 Skill。
- `pm-subtask`（前置/后置生成）：pm-daily 调（前置）、`/pm 完成` 调（后置），type 参数区分。
- `pm-summary`：用户指令、21:00 提醒、周日 12:00，均调同一 Skill。
- `TaskAppSvc`（任务完成+级联）：pm-subtask 内调、智能体验收通过、看板标记完成，均调同一 Service 方法。

---

# 九、Skill 与 Gateway 协作关系

```
用户消息
  │
  ▼
Gateway（Hermes Agent）
  ├── 生成类（规划/今日计划/完成/总结）→ 子 Skill
  ├── /pm 确认完成 → 硬编码路由 → POST /tasks/{id}/confirm-complete
  ├── 配置类（配置/关联项目空间）→ pm LLM 提取参数 → 生成预填 H5 链接
  └── 其他 → LLM 通用对话

定时任务
  ├── 8:30 → pm-daily Skill
  ├── 21:00 → pm-summary Skill（或仅提醒）
  └── 周日 12:00 → pm-summary Skill

卡片按钮点击 / H5 页面提交
  │
  ▼
Gateway 解析 action_id / H5 调 Service API
  ├── story1_确认方案 → POST /plans/confirm（用 draft_id）
  ├── story2_下一步 → patch 卡片为填 deadline
  ├── story2_确认调度 → POST /schedules/confirm
  ├── story3_确认今日计划 → POST /daily/confirm
  ├── story4A_验收通过 → POST /tasks/{id}/output/confirm
  ├── story4A_需要修改 → POST /tasks/{id}/output/reject
  ├── story4B_确认后置/不需要后置 → POST /tasks/{id}/post-confirm
  ├── story5_标记完成/未完成 → PATCH /tasks/{id}（即时级联+刷新卡片）
  ├── story5_确认日终总结 → POST /daily/summary/confirm
  ├── story6_已阅 → POST /weekly/summary/confirm
  ├── story8_确认激活 → POST /schedules/activate
  ├── H5 字段编辑 → PUT /board/{entity}/{id}
  ├── H5 状态变更 → POST /board/{entity}/{id}/status
  ├── H5 任务删除 → DELETE /tasks/{id}
  └── H5 模板 CRUD → /subtask-templates
```

---

# 十、Skill 错误处理策略

| 错误场景 | Skill 行为 | 用户感知 |
|----------|-----------|----------|
| Service API 返回 1001（资源不存在） | 重新查询或引导 | "未找到相关目标，请确认名称" |
| Service API 返回 1003（状态冲突） | 展示当前状态 | "该阶段已处于进行中" |
| Service API 返回 1004（并发超限） | 展示当前活跃阶段 | "当前已有 3 个进行中阶段" |
| Service API 返回 1005（回退需 reason） | 引导补充 reason | "回退需说明原因" |
| Service API 返回 1007（草稿过期） | 重新生成 | "草稿已过期，重新规划" |
| Service API 返回 3001（模板已存在） | 提示覆盖 | "该配置项已存在" |
| Service API 返回 5000（内部错误） | 重试 1 次，仍失败通知 | "服务异常，请稍后重试" |
| LLM 生成异常 | 重新生成或降级 | "让我重新整理一下..." |
| 卡片发送失败 | 降级纯文本 | 纯文本展示 |
| 意图无法识别 | 澄清提问 | "请问您是想...还是...？" |

---

# 十一、Skill 配置参数

```yaml
pm-plan:
  max_clarification_rounds: 3
  default_theme_count: 4
  default_phase_per_theme: 3
  # 提问引导策略（配置在 Skill 里）：
  # 1. 专题构成 → 2. 目标时间范围 → 3. scheduled_start_date → 4. 逐专题阶段任务
  card_template: "plan_overview_v1"  # 总览卡片（只展示概览）

pm-daily:
  default_daily_task_count: 5
  min_daily_task_count: 3
  candidate_count: 8  # 候选任务数（5-8）
  max_active_phases: 3  # 全局进行中阶段上限（已暂停不占名额）
  daily_push_time: "08:30"
  # executor 推断规则（按专题 type）：
  # learning/research/source → human
  # dev/survey → agent
  card_template_daily: "daily_plan_v1"  # 任务勾选+前置勾选（两组独立）

pm-subtask:
  default_post_subtasks:
    learning: ["笔记归档", "总结生成", "自测题生成"]
    dev: ["代码 review", "文档更新", "测试运行"]
    research: ["文献归档", "笔记整理", "引用生成"]
    survey: ["选型对比表归档", "验证脚本整理"]
    source: ["资源归档", "标签整理"]
  # 前置按今日整体生成（不按单个任务）
  # 后置按单个任务生成，和完成脱钩
  card_template_post: "post_subtask_v1"  # 默认全选，可取消，可全取消

pm-summary:
  summary_reminder_time: "21:00"
  weekly_summary_time: "12:00"
  card_template_summary: "daily_summary_v1"  # 状态切换按钮（双向）
  card_template_weekly: "weekly_summary_v1"

# Service 层配置（非 Skill）
agent:
  opencode_base_url: "http://localhost:8080"
  opencode_timeout: 7200
  max_retry_count: 3
  retry_backoff: [0, 300, 600]

supervisor:
  deadline_warning_days: 1
  plan_reminder_time: "10:00"
  summary_reminder_time: "21:00"
  next_phase_reminder_hours: 24
  # 卡顿监测暂不做

config:
  max_templates_per_scope: 20
```
