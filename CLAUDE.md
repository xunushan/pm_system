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
| 07_决策文档_v1.0.md | 历轮决策记录（D1-D24） |

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
- **每实现一个 model，在 `app/models/__init__.py` import 它**（Alembic autogenerate 才看得到）。

### 风格
- ruff（line-length 100，规则 E/F/I/UP/B）。提交前 `make lint`、`make format`。
- Python 3.11+ 语法（`str | None` 等）。

## 五、开发流程（Story 纵向切片）

按依赖顺序逐 Story 实现，每个 Story 完整贯通（model → migration → repo → service → api → test），**测试全绿才进下一个**。

### 每 Story 步骤
1. 读对应文档章节（见下方对照表）
2. 写/改 `app/models/*.py`，在 `__init__.py` import
3. `make migrate MSG="..."` 生成迁移，**检查迁移文件**无误
4. `make upgrade` 应用
5. 写 Repository（如需）
6. 写 AppSvc（业务 + 事务 + 级联）
7. 写 `app/api/v1/*.py` 路由
8. 写测试（`tests/unit` + `tests/integration`）
9. `make test` 全绿 → 进下一个 Story

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
