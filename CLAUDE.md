# CLAUDE.md - 目标管理系统开发规范

> 智能体开发本系统时**必读**本文件。本文件只放铁律 + 指针，流程细节见引用文件。
> 设计文档在 `doc/`（只读，实现时引用，勿改）。
> 铁律是行为准则（违反即返工）；技术决策见 doc/07。

## 一、项目概述

个人目标管理系统：飞书聊天 + 卡片 + H5 页面三入口驱动目标拆解、调度、执行、总结。

- **交互层**：Hermes Agent（本地）+ 5 Skill（pm/pm-plan/pm-daily/pm-subtask/pm-summary）
- **服务层**：FastAPI + SQLAlchemy + SQLite + Redis（**自研核心**）
- **执行层**：OpenCode（本地 CLI，智能体执行任务）

技术栈：Python 3.11+ / uv / FastAPI / SQLAlchemy 2 / Alembic / pytest / ruff；H5：React18 + Vite + TS。

## 二、文档索引（渐进式读取的根基）

> 子 agent 开发/review 时**只读必需子文件**，不读全文档。本索引是渐进式披露的入口。
> 文档治理范式见 doc/10；任务管理见 doc/11。

| 文档 | 内容 | 入口 |
|------|------|------|
| doc/01 | 用户故事（9 Story，what/why） | doc/01_用户故事文档_v2.0.md |
| doc/02 | 数据模型（14 表 + 状态机 + 级联） | doc/02_数据模型文档_v2.0.md |
| doc/03 | 系统架构（分层 + 组件 + 集成约束） | doc/03_系统架构文档_v2.0.md |
| doc/04 | 服务 API（REST + webhook + drafts） | doc/04_服务API文档_v2.0.md |
| doc/05 | Skill 设计（5 Skill 职责边界） | doc/05_Skill设计文档_v2.0.md |
| doc/06 | 卡片按钮路由清单（入口 B action_id/btn_name 对照） | doc/06_操作流程与技术动作清单_v2.0.md |
| doc/07 | 关键决策（ADR：DECISION + FACT） | doc/07_决策文档_v1.0.md |
| doc/08 | 教训（v2 验证 L1-L6） | doc/08_教训文档.md |
| doc/09 | UI 卡片交互样式（纯 UI，schema 2.0） | doc/09_卡片交互样式记录.md |
| doc/10 | 文档治理范式 | doc/10_文档治理范式.md |
| doc/11 | 任务管理方案 | doc/11_任务管理方案.md |
| doc/13 | 原型验证（飞书卡片 + opencode 集成验证事实） | doc/13_原型验证/ |

**实现任何功能前，按本索引读对应文档章节**（不读全文档）。Story 与文档对照见 docs/process/story-map.md。

## 三、铁律（行为准则，违反即返工）

> 铁律 = 项目无关的行为准则，全模块每次适用。技术决策（Service 不调 LLM 等）见 doc/07，不在此。

1. **即时级联在事务内**。任务/阶段状态变更时事务内向上级联（纯 DB，<200ms）；副作用（工作空间初始化、异步执行、推送）事务提交后异步。**事务内禁止 IO/HTTP**。
2. **飞书回调 3 秒超时**。确认类 API 仅做 DB 写 + 即时级联，立即返回。耗时操作必须异步。
3. **状态机约束**。回退/暂停必填 reason；恢复不填 reason。所有流转写 `status_change_log`。
4. **卡片点击后必须刷新**。所有回调点击后必须 update_card（按钮灰化/反转/消失），禁止"点击后卡片不变"。
5. **测试全绿才进下一步**。每个 Story 完成前 `make test` 必须**全绿**；新功能必须有测试（单元 + 集成）。测试用内存 SQLite + StaticPool，不碰真实 DB。`make lint` 通过。
6. **先搜后建**。实现任何新逻辑前，先 grep 现有代码（`grep -rn "关键词" app/core/ app/clients/ app/services/`）。有现成实现则调用，没有才新建。**重复造轮子是 P1 issue**。
7. **提交规范**。Conventional Commits（`<type>(<scope>): <subject>`，type: feat/fix/refactor/test/docs/chore/perf，scope: plan/daily/task/board 等）。PR title 必须含 Story 号。**合并用 squash**。合并是主 agent 职责，子 agent 不自行合并。

## 四、开发流程指针

> 流程详情见引用文件，本节只放指针 + skill 触发。

### Story 纵向切片流程
按依赖顺序逐 Story 实现（model -> migration -> repo -> service -> api -> test），**测试全绿才进下一个**。每 Story 步骤见 docs/process/dev-flow.md。

### skill 触发指针
- **任务拆分**：读 doc/ 设计文档 -> 调 `spec-to-tasks` skill（vertical slice + quiz user + 发布 issue）
- **任务推进**：接手/派发/验证/CI监控/合并/冲突 -> 调 `task-advance` skill（流程详见 doc/11 §八）
  - 含模型选择（机械->haiku，业务->sonnet，reviewer 固定 sonnet）

### 复用件清单（必须复用，禁止重写）
| 件 | 位置 | 用途 |
|----|------|------|
| 即时级联引擎 | `app/core/cascade.py` | 任务/阶段状态变更事务内向上推导 |
| 状态机校验 | `app/core/state_machine.py` | 状态流转合法性 + reason 必填 |
| 状态变更审计 | `app/core/audit.py` | 写 status_change_log |
| 飞书客户端 | `app/clients/feishu.py` | 发消息/更新卡片/发文件 |
| OpenCode 客户端 | `app/clients/opencode.py` | 下发任务到 opencode serve |
| Obsidian 读写 | `app/clients/fileio.py` | daily.md/weekly.md 快照 |
| 事件总线 | `app/supervisor/event_bus.py` | 状态变更事件分发 |

用法：`from app.core import cascade, state_machine, audit`。事件总线 S8 实现，S1 起调 emit() 桩。

### 迁移合并纪律
- 迁移文件生成后检查无误再 upgrade；**迁移合并由主 agent 执行**，不让子 agent 自合。
- 多 head / 串行合 / 冲突解决细节见 task-advance 阶段 5（doc/11 §八）或 docs/process/migration-merge.md。

### 主 agent 职责与转交
**主 agent 自留**（产出是判断/决策/交互，无法机械验证、需对全局负责）：
- 调度：定位下一个任务、派发子 agent、设模型、合并 PR、更新 PROGRESS/doc/07。
- 决策：PR 能否合、偏差是否真问题、优先级、模型选型判断。
- 用户面：澄清需求、汇报进度、AskUserQuestion、视觉确认转述。
- 门面：子 agent 输出返回主 agent，主 agent 决定转述/追问/返工。子 agent 不直接和用户对话。

**转交子 agent**（产出是可验证的制品，验证标准明确、可独立完成、可审查）：
- 代码实现（make test 验证）
- code review（独立 agent，报告可读；与实现 agent 必须分开）
- research（带引用文档）
- spike / prototype（answer 验证，FACT 入 doc/07）
- 机械任务批量（ORM/repo/route/migration）

> 判据：产出是"可验证制品"-> 转交；产出是"判断/决策/交互"-> 主 agent 自留。

## 五、会话恢复协议

新 session 接手调 `task-advance` skill（阶段 1 接手三板斧）：读 PROGRESS.md -> 核对 git/issue -> 交叉比对（矛盾以 git 为准）。
- git 是真相源（log/branch/pr/issue），PROGRESS.md 是缓存。
- 定位下一步：第一个"未合并"且"其依赖已全部合并到 main"的任务。
- 流程详见 doc/11 §八 task-advance 阶段 1。

## 六、关键约束速查 + 门禁策略

### 飞书卡片
- 卡片避免一次性传大数据，只展示概览，回调只传标识符（draft_id/task_id）。
- 卡片刷新用 message_id 调"更新消息"接口。
- 飞书卡片不支持级联选择 -> Story2 用 patch 卡片。
- 细节见 doc/09（纯 UI）/ doc/07（飞书 API 行为 FACT）。

### 三入口
- **入口 A**（聊天）：飞书 -> Hermes -> Skill -> Service `/api/v1`。进讨论态。
- **入口 B**（卡片回调）：飞书 -> Service `/webhook/feishu/card` -> 硬编码 action_id 路由 -> AppService -> 事务。
- **入口 C**（H5 页面）：浏览器 -> Service `/api/v1/board/*` -> 校验落库。

### 状态机（doc/02）
- 阶段：未开始/进行中/已完成/已暂停；进行中↔已暂停、已完成->进行中(revert,reason必填)
- 任务：待执行/已完成/已暂停；待执行↔已暂停、已完成->待执行(revert,reason必填)
- 暂停/回退必填 reason，恢复不填 reason

### 文档引用规范（代码注释 / 文档交叉引用）
- **禁止用行号引用**（`doc/0X line 572`、`doc/0X 行654`、`doc/0X:NNN`）。文档增删一行即错位，行号是位置快照不是身份锚。
- **用结构锚 + 内容提示**：`doc/0X S<N>`（Story 号）或 `doc/0X §<N.N>`（章节号），后接 `（一句内容）`。内容提示是 grep 锚，结构漂移时也能靠内容找回。
- 形态：`doc/0X S<N>｜§<N.N>（一句内容）`。例：`doc/01 S2 AC：激活后不能修改项目空间模式` / `doc/04 §3.7 POST /tasks/{id}/complete`。
- 错误码、章节号本身（`doc/04 1004`、`doc/02 2.16`）是稳定的，保留。

### 门禁策略
- **CI 硬门禁**：`Service (lint+test+migrate)` 和 `H5 (build)` 必须全绿才能合并。
- **strict 模式**：分支必须 rebase 到最新 main。
- **线性历史**：只允许 squash 合并。
- **review 软门禁**：code-reviewer agent 以报告形式（`gh pr review --comment`）提供，主 agent 基于报告决定。CI 是唯一平台级硬门禁。
- **docs/migration 跳 review**：纯 docs / 纯 alembic migration 的 PR 可跳过 code-reviewer（无业务逻辑可审），CI 全绿即可合。含业务逻辑的 PR 必须过 review。

### issue 模板选型
开 issue 时主 agent 据类型选 `.github/ISSUE_TEMPLATE/` 下的 form：
- bug（复现+期望+实际+严重度）/ feature（What/Acceptance/Blocked by）/ spike（问题+方法+期望产出）/ chore / docs。
- issue 只放任务自身信息，不放项目绑定字段（铁律/复用件归本文件，子 agent 读 CLAUDE.md 获取）。
- 标签 3 维：状态（needs-triage/ready-for-agent/...）+ 类型（bug/feature/spike/chore/docs）+ 优先级（P0-P3）。详见 doc/11 §二。

### CI 监控
等 PR check 完成（决定是否合并）调 `task-advance` 阶段 4（`gh pr checks <N> --watch`，阻塞到终态退出即通知）。命令详见 doc/11 §八。

## 七、常用命令速查

```
make install                              # 装所有依赖（service + h5）
make dev                                  # 起 Service :8001（热重载）
make test                                 # 跑测试
make migrate MSG="add themes phases tasks" # 生成迁移
make upgrade                              # 应用迁移
make lint / make format                   # 检查/格式化
make h5-dev                               # 起 H5 :5173
make up / make down                       # Docker（service + redis）
```

Service 内：`uv run pytest`、`uv run uvicorn app.main:app --reload`、`uv run alembic ...`
H5 内：`npm run dev`、`npm run build`

## 八、协作规范（多 agent + GitHub）

### worktree + 分支（避免分支互写）
- 每个任务一个 worktree + 一个分支，分支名 `feat/story-N`（或 milestone/feature 命名，粒度无关见 doc/11 §七）。
- 派发子 agent 时设 `isolation: "worktree"`。
- **worktree 生命周期 = 任务生命周期**：合并后立即删 worktree + 删分支。
- 子 agent 开工前必做：`git fetch && git rebase origin/main`。

### PR 流程
```
开发 agent 完成 -> push feat/story-N -> gh pr create
  -> GitHub Actions CI 自动跑（ruff + pytest + alembic）【硬门禁】
  -> 主会话派 code-reviewer agent 审查 -> 产出报告（gh pr review --comment）【软门禁】
  -> 报告有 P0/P1 -> 转回开发 agent 修 -> push（CI 重跑，review 重审）
  -> CI 绿 + review 无 P0/P1（或 docs/migration 跳 review）-> 主会话 gh pr merge --squash --delete-branch
  -> PR 写 Fixes #N 则对应 issue 自动关闭
  -> 更新 PROGRESS.md
```

### issue 闭环
issue 必须**自包含**（完整复现步骤 + 期望 + 实际），因为修复 agent 无上下文记忆。
```
提 issue（关联 Story + 严重度）-> 分配
  -> agent 读 issue 复现 -> 修 -> 加回归测试 -> 开 PR（Fixes #N）
  -> review 复测 -> 通过合并 -> issue 自动关闭 / 不通过 gh issue reopen
```
