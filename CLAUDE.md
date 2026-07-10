# CLAUDE.md — 目标管理系统开发规范

> 智能体开发本系统时**必读**本文件。本文件定义架构铁律、代码规范、开发流程。
> 设计文档在 `doc/`（**只读**，实现时引用，勿改）。

## 一、项目概述

个人目标管理系统：飞书聊天 + 卡片 + H5 页面三入口驱动目标拆解、调度、执行、总结。

- **交互层**：Hermes Agent（本地）+ 5 Skill（pm/pm-plan/pm-daily/pm-subtask/pm-summary）
- **服务层**：FastAPI + SQLAlchemy + SQLite + Redis（**自研核心**）
- **执行层**：OpenCode（本地 CLI，智能体执行任务）

技术栈：Python 3.11+ / uv / FastAPI / SQLAlchemy 2 / Alembic / pytest / ruff；H5：React18 + Vite + TS。

## 二、设计文档索引（doc/，只读）

| 文档 | 内容 |
|------|------|
| 01_用户故事文档_v2.0.md | 9 个 Story 的用户视角流程 |
| 02_数据模型文档_v2.0.md | 14 表 + 视图 + 索引 + 状态机 + 级联规则 |
| 03_系统架构文档_v2.0.md | 双层架构 + Supervisor + H5 + 约束 8.1-8.21 |
| 04_服务API文档_v2.0.md | REST 接口 + webhook + drafts |
| 05_Skill设计文档_v2.0.md | 5 Skill 职责边界 |
| 06_操作流程与技术动作清单_v2.0.md | 每 Story 操作流程 + 指令/卡片/H5/定时表 |
| 07_决策文档_v1.0.md | 历轮决策记录（D1-D25，含推翻项） |
| 08_教训文档.md | v2 验证教训 L1-L6 + 测试三分 + 行业标准 + 检查清单 |

**实现任何功能前，先读对应文档章节。**

## 三、架构铁律（违反即返工）

1. **Service 不调用 LLM**。所有 LLM 交互由交互层 Skill 完成。需 LLM 的（规划/前置/后置/总结/异议）走 Skill；纯确定性逻辑（级联、状态机、deadline 推算、executor 推断）是 Service 代码。
2. **讨论态 vs 执行态分离**。聊天只进讨论态，不写库；只有结构化回调（卡片按钮 `/webhook`、H5 页面 API）触发执行态事务。
3. **即时级联在事务内**。任务/阶段状态变更时事务内向上级联（纯 DB，<200ms）；副作用（工作空间初始化、异步执行、推送）事务提交后异步。
4. **飞书回调 3 秒超时**。确认类 API 仅做 DB 写 + 即时级联，立即返回。耗时操作必须异步。
5. **DB 唯一真相源**。H5 页面调 Service API 落库，无反向同步（无多维表格）。
6. **drafts 规避飞书回调 30KB**。pm-plan 规划数据存 drafts（content 存完整 JSON），确认按钮回调只传 draft_id。
7. **状态机约束**（doc/02 2.16）。回退/暂停必填 reason；恢复不填 reason。所有流转写 `status_change_log`。
8. **executor 规划态不填**。任务规划时 executor=NULL，pm-daily 按专题 type 推断填入（learning/research/source→human；dev/survey→agent）。
9. **前置整体 / 后置脱钩**。前置按今日整体生成（与任务解耦，任务勾选变化**不**重生成前置）；后置按单个任务生成且和完成脱钩（完成即时级联，后置可全取消）。
10. **专题无序 + 阶段强约束**。专题无 sort_order；阶段按 sort_order 顺序激活，自动锁定第 1 个未开始阶段。
11. **卡片全生命周期归 Service**（doc/07 D25）。Service 拥有构建（build_*_card）+ 发送（send_card/update_card/send_file）+ 回调路由（/webhook action_id）+ 点击后刷新（update_card 重建整张卡）；Skill 只调 Service 推卡方法。开发期 Skill 缺位时，"Skill 推卡"场景必须有等价 Service 推卡方法兜底。所有回调点击后必须 update_card（按钮灰化/反转/消失，禁止"点击后卡片不变"）；message_id 优先从飞书回调 payload 顶层取（飞书卡片回调含被点击卡片的 message_id），fallback 从 action_value 取（待 e2e TC-S5-01 实测确认取法）。按钮置于对应项旁（per-item），禁止全挤一个 action 块。

## 四、代码规范

### 分层（service/app/）
`api/`（路由，薄）→ `services/`（AppSvc，业务+事务+级联）→ `repositories/`（纯 CRUD）→ `models/`（ORM）。

- 命名：AppSvc 后缀 `XAppSvc`，Repository 后缀 `XRepository`。
- 路由只做参数校验 + 调 AppSvc，不写业务。
- Repository 不含业务逻辑、不调 LLM、不发 HTTP。

### 事务
- 事务由 AppSvc 管理。
- **事务内禁止 IO/HTTP**。模式：写 DB + 即时级联 → commit → 异步 IO/HTTP。
- 级联用 `app/core/cascade.py`，审计用 `app/core/audit.py`，状态机用 `app/core/state_machine.py`。

### 数据
- 主键：TEXT，UUID（`uuid4`）。
- 时间：UTC 存储。
- model 范本见 `app/models/goal.py`（Mapped 类型 + CheckConstraint + server_default）。
- **新增 model：在 `app/models/` 下新建 `*.py` 即可**，`__init__.py` 自动发现（无需手动加 import，消除多 agent 并行编辑冲突）。Alembic autogenerate 会自动检测到。

### 风格
- ruff（line-length 100，规则 E/F/I/UP/B）。提交前 `make lint`、`make format`。
- Python 3.11+ 语法（`str | None` 等）。

## 五、开发流程（Story 纵向切片）

按依赖顺序逐 Story 实现，每个 Story 完整贯通（model → migration → repo → service → api → test），**测试全绿才进下一个**。

### 每 Story 步骤
1. 读对应文档章节（见下方对照表）
2. 写/改 `app/models/*.py`（新文件自动被 `__init__.py` 发现，无需改它）
3. `make migrate MSG="..."` 生成迁移，**检查迁移文件**无误
4. `make upgrade` 应用
5. 写 Repository（如需）
6. 写 AppSvc（业务 + 事务 + 级联；复用 `app/core/` 现有件）
7. 写 `app/api/v1/*.py` 路由（在 `router.py` 注册）
8. 写测试（`tests/unit` + `tests/integration`）
9. `make test` + `make lint` 全绿后提交（提交规范见第十节）

### Story 顺序与文档对照
| 顺序 | Story | 涉及表/组件 | 文档 |
|------|-------|------------|------|
| 1 | Story1 目标规划与确认 | goals/themes/phases/tasks/drafts | 01 S1 · 02 2.2-2.3/2.9 · 04 规划+drafts · 05 pm-plan |
| 2 | Story2 调度激活（含项目空间） | workspaces/phases 激活 | 01 S2 · 02 2.4 · 04 调度+项目空间 · 06 |
| 3 | Story3 当日计划推送 | daily_records/daily_tasks/executor 推断/前置 | 01 S3 · 02 2.8 · 04 今日计划 · 05 pm-daily |
| 4a | Story4A 智能体执行 | agent_processes/workspace_progress/opencode | 01 S4A · 02 2.7/2.10 · 04 智能体进程 · 03 五 |
| 4b | Story4B 人完成任务 | subtasks(后置) | 01 S4B · 02 2.5 · 04 子任务 · 05 pm-subtask |
| 5 | Story5 日终总结 | status_change_log(回退) | 01 S5 · 02 2.11/2.16 · 04 日终 · 05 pm-summary |
| 6 | Story6 周总结 | weekly_records | 01 S6 · 02 2.8 · 04 周总结 |
| 7 | Story7 子任务配置 | subtask_templates | 01 S7 · 02 2.6 · 04 配置 |
| 8 | Story8 主动巡检与阶段衔接 | supervisor(event_bus/scheduler/handlers) | 01 S8 · 03 三 · 06 定时表 |
| 9 | Story9 轻量编辑与状态回退 | board/H5 编辑/回退 | 01 S9 · 03 四 · 04 看板 |

> Story9 依赖前面所有表，放最后。原"项目空间设置"已并入 Story2 卡片 A。

## 六、测试门禁

- 每个 Story 完成前 `make test` 必须**全绿**。
- 新功能必须有测试：单元（级联/状态机/executor 推断）+ 集成（API + DB）。
- 测试用内存 SQLite + StaticPool（见 `tests/conftest.py`），不碰真实 DB。
- `make lint` 通过。

## 七、常用命令

```
make install                              # 装所有依赖（service + h5）
make dev                                  # 起 Service :8001（热重载）
make test                                 # 跑测试
make migrate MSG="add themes phases tasks" # 生成迁移
make upgrade                              # 应用迁移
make lint / make format                   # 检查/格式化
make h5-dev                               # 起 H5 :5173
make up / make down                        # Docker（service + redis）
```

Service 内：`uv run pytest`、`uv run uvicorn app.main:app --reload`、`uv run alembic ...`
H5 内：`npm run dev`、`npm run build`

## 八、框架层既有决策（与文档的差异，开发时遵从）

1. **端口收口为 8001**。架构文档概念上是 8001(REST)+8002(webhook)两端口，但同一 FastAPI app 服务两个前缀，单进程单端口（8001）更简单。`/webhook/feishu/card` 在 8001 上。如后续需 8002 公网隔离，加 nginx/proxy。
2. **drafts/goals 已建骨架**：goals 为 model 范本，drafts 等其余 13 表按 Story 实现。
3. **alembic versions/ 当前为空**，首个迁移由 Story1 生成（goals+themes+phases+tasks+drafts）。
4. **Skills 仅 SKILL.md 占位**（跟随 Hermes 约定），实际 Skill 代码实现时需参考 Hermes 框架文档。
5. **H5 页面设计暂不讨论**，仅骨架 + 健康检查联通。

## 九、关键约束速查

### 飞书卡片
- 卡片避免一次性传大数据，只展示概览，回调只传标识符（draft_id/task_id）。
- 卡片刷新用 message_id 调"更新消息"接口。
- 飞书卡片**不支持级联选择**（cascader）→ Story2 用 patch 卡片（选专题 → patch 填 deadline）。
- 多选专题 + managed/path 在卡片 A，deadline 在卡片 B。

### 三入口
- **入口 A**（聊天）：飞书 → Hermes → Skill → Service `/api/v1`。进讨论态。
- **入口 B**（卡片回调）：飞书 → Service `/webhook/feishu/card` → 硬编码 action_id 路由 → AppService → 事务。
- **入口 C**（H5 页面）：浏览器 → Service `/api/v1/board/*` → 校验落库。

### 状态机（doc/02 2.16）
- 阶段：未开始/进行中/已完成/已暂停；进行中↔已暂停、已完成→进行中(revert,reason必填)
- 任务：待执行/已完成/已暂停；待执行↔已暂停、已完成→待执行(revert,reason必填)
- 暂停/回退必填 reason，恢复不填 reason


---

## 十、会话恢复协议（agent 重启必做）

agent 上下文会被压缩或丢失，**不依赖对话记忆恢复进度**。新 session 接手时按以下顺序恢复，git/代码是真相源，PROGRESS.md 是缓存：

1. **读本文件**（CLAUDE.md）：了解规范、铁律、Story 顺序。
2. **看进度缓存**：读 `PROGRESS.md` 状态表（可能滞后，下一步交叉验证）。
3. **看 git 真相**：
   - `git log --oneline origin/main | grep -oE 'Story [0-9A-Za-z]+'`：已合并的 Story
   - `git branch -r | grep feat/story`：进行中的分支
4. **看 PR/issue**：
   - `gh pr list --state open --json number,title,headRefName`：审查中的 PR
   - `gh issue list --state open`：未修的 bug
5. **看代码级进度**：`app/models/__init__.py` 的 ✅/⬜ 进度表（最细）
6. **交叉比对**：若 PROGRESS.md 与 git 矛盾，以 git 为准，顺手更新 PROGRESS.md。
7. **定位下一步**：第一个"未合并"且"其依赖已全部合并到 main"的 Story = 下一个要做的。

恢复命令一键脚本：
```bash
echo "=== 已合并 Story ===" && git log --oneline origin/main | grep -oE 'Story [0-9A-Za-z]+' | sort -u
echo "=== 进行中分支 ===" && git branch -r | grep feat/story
echo "=== 开放 PR ===" && gh pr list --state open
echo "=== 开放 issue ===" && gh issue list
```

## 十一、复用件清单 + 先搜后建纪律

### 必须复用、禁止重写的公共件
| 件 | 位置 | 用途 | 被哪些 Story 复用 |
|----|------|------|------------------|
| 即时级联引擎 | `app/core/cascade.py` | 任务/阶段状态变更事务内向上推导 | S5(回退)、S9(看板)、S8(监听事件) |
| 状态机校验 | `app/core/state_machine.py` | 状态流转合法性 + reason 必填 | S5、S9 |
| 状态变更审计 | `app/core/audit.py` | 写 status_change_log | S5、S8、S9 |
| 飞书客户端 | `app/clients/feishu.py` | 发消息/更新卡片/发文件 | 所有推卡片的 Story |
| OpenCode 客户端 | `app/clients/opencode.py` | 下发任务到 opencode serve | S4A |
| Obsidian 读写 | `app/clients/fileio.py` | daily.md/weekly.md 快照 | S5、S6 |
| 事件总线 | `app/supervisor/event_bus.py` | 状态变更事件分发 | S8 实现，S1-S7 调 emit() |

用法：`from app.core import cascade, state_machine, audit`。

### 事件总线接口先行
S8 才实现 EventBus，但 S1 起就会发"阶段完成"事件。**S1 建一个 `emit(event)` 桩**（先 no-op 只打日志），S1-S7 都调 `emit()`，S8 把内部实现换成真分发。接口不变，S8 合并后之前所有事件自动接上。

### 先搜后建（硬规则）
**实现任何新逻辑前，先 grep 现有代码**：
```bash
grep -rn "关键词" app/core/ app/clients/ app/services/
```
有现成实现则调用，没有才新建。**重复造轮子是 P1 issue**（code-reviewer 会查）。

## 十二、协作规范（多 agent + GitHub）

### 角色分工
- **主会话（你）**：调度中心。定位下一个 Story、派发子 agent、合并 PR、更新 PROGRESS.md。**主工作区只做合并，不写业务代码**。
- **开发子 agent**：在 worktree 里实现一个 Story，写完+测试+开 PR 后汇报。
- **code-reviewer agent**（`.claude/agents/code-reviewer.md`）：审 PR，只报不改。通用方法论 + 读 CLAUDE.md 注入本项目铁律。

### worktree + 分支（避免分支互写）
- 每个 Story 一个 worktree + 一个分支，分支名 `feat/story-N`（如 `feat/story-2`）。
- 派发子 agent 时设 `isolation: "worktree"`，自动在 `.claude/worktrees/storyN/` 建隔离目录。
- **worktree 生命周期 = Story 生命周期**：合并后立即删 worktree（`git worktree remove`）+ 删分支。
- 子 agent 开工前必做：`git fetch && git rebase origin/main`（基要最新）。
- 子 agent 不自行合并，合并是主会话职责。

### 提交规范（Conventional Commits，来源 conventionalcommits.org）
格式：`<type>(<scope>): <subject>`
- type：feat / fix / refactor / test / docs / chore / perf
- scope：模块名（plan/daily/task/board 等）
- **PR title 必须含 Story 号**：如 `feat(plan): Story1 目标规划与确认`

commit 示例：
```
feat(plan): Story1 目标规划与确认
fix(daily): executor 推断漏处理 learning 类型
test(cascade): 补充回退级联回归测试
```

PR 描述必须含（见 `.github/PULL_REQUEST_TEMPLATE.md`）：实现内容、关联 Story、依赖、Fixes #issue、测试结果、铁律自检。**合并用 squash**（一个 Story = main 上一条提交，可数）。

### 合并顺序（严格按依赖图）
合并顺序 = 依赖顺序（见第五节 Story 表）。同一并行窗口（如 {S2‖S7}）必须**一个合完、main 更新后，另一个 rebase 再合**，不能同时合。

### 迁移合并纪律（alembic 多 head 处理）
并行 Story 各自生成迁移文件，合并到 main 时**按顺序串行合**：
1. 合第一个 Story：正常 `gh pr merge --squash`。
2. 合第二个 Story 前：该分支 `git rebase origin/main`。
3. 若 alembic 报 "Multiple heads"（两个迁移都指向旧 head）：
   - 方案 A（推荐）：`uv run alembic merge -m "merge storyX storyY" <revX> <revY>` 生成合流迁移。
   - 方案 B：手动把后者的 `down_revision` 改指新 head。
4. `uv run alembic upgrade head` 验证无误后，才合并。
5. **迁移合并由主会话执行，不让子 agent 自己合。**

### PR 流程
```
开发 agent 完成 -> push feat/story-N -> gh pr create
  -> GitHub Actions CI 自动跑（ruff + pytest + alembic）【硬门禁】
  -> 主会话派 code-reviewer agent 审查 -> 产出报告（gh pr review --comment）【软门禁】
  -> 报告有 P0/P1 -> 转回开发 agent 修 -> push（CI 重跑，review 重审）
  -> CI 绿 + review 无 P0/P1 -> 主会话 gh pr merge --squash --delete-branch
  -> PR 写 Fixes #N 则对应 issue 自动关闭
  -> 更新 PROGRESS.md
```

### 分支保护（已配置）
- **CI 硬门禁**：`Service (lint+test+migrate)` 和 `H5 (build)` 必须全绿才能合并。
- **strict 模式**：分支必须 rebase 到最新 main。
- **线性历史**：只允许 squash 合并（一个 Story = main 上一条提交）。
- **不强制 GitHub approval**：单人 + 智能体场景，PR 作者即代码作者，GitHub 不允许作者批准自己的 PR。故 review 由 code-reviewer agent 以**报告形式**（`gh pr review --comment`）提供，主会话基于报告决定是否合并（软门禁，靠纪律）。CI 是唯一的平台级硬门禁。

### issue 闭环
issue 必须**自包含**（完整复现步骤 + 期望 + 实际），因为修复 agent 无上下文记忆。
```
提 issue（关联 Story + 严重度）-> 分配给该 Story 的负责 agent
  -> agent 读 issue 复现 -> 修 -> 加回归测试 -> 开 PR（Fixes #N）
  -> review 复测 -> 通过合并 -> issue 自动关闭 / 不通过 gh issue reopen
```
主会话启动时一次性 `gh issue list` + `gh pr list` 同步状态，**无需定时扫描**。