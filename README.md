# 目标管理系统

个人目标管理系统：飞书聊天 + 卡片 + H5 页面三入口驱动目标拆解、调度、执行、总结。

## 架构

- **交互层**：Hermes Agent（本地）+ 5 Skill（pm/pm-plan/pm-daily/pm-subtask/pm-summary）
- **服务层**：FastAPI + SQLAlchemy + SQLite + Redis（自研核心）
- **执行层**：OpenCode（本地 CLI，智能体执行任务）

设计文档见 `doc/`（7 份）。开发规范见 [`CLAUDE.md`](./CLAUDE.md)（智能体必读）。

## 快速开始

### 前置
- Python 3.11+、[uv](https://docs.astral.sh/uv/)、Node 18+
- （可选）Redis、Docker

### 安装
```bash
make install                                    # 装 service + h5 依赖
cp service/.env.example service/.env            # 配环境变量
```

### 起服务
```bash
make dev      # Service :8001（热重载）
make h5-dev   # H5 :5173
```
- API 文档：http://localhost:8001/docs
- H5 页面：http://localhost:5173

### 测试 / 迁移
```bash
make test
make migrate MSG="add themes phases tasks"     # 生成迁移
make upgrade                                    # 应用迁移
make lint
```

### Docker（service + redis）
```bash
make up      # 起服务（自动跑迁移）
make down    # 停
```

## 目录结构

```
doc/                  设计文档（只读，7 份）
service/              Service 层（FastAPI，自研核心）
  app/
    api/v1/           路由（11 个业务域）
    services/         AppSvc（11 个，业务+事务+级联）
    repositories/     纯 CRUD
    models/           ORM（14 表，goals 为范本）
    core/             cascade/state_machine/audit
    supervisor/       event_bus/scheduler/handlers（Story8）
    clients/          feishu/opencode/fileio
    webhook/          /webhook/feishu/card（入口 B）
  alembic/            迁移
  tests/              unit + integration
h5/                   React + Vite 前端
skills/               Hermes Skills（5 个 SKILL.md）
docker-compose.yml    service + redis
Makefile              常用命令
CLAUDE.md             开发规范（智能体必读）
```

## 开发

按 Story 纵向切片开发，顺序与规范见 [`CLAUDE.md`](./CLAUDE.md)。
当前进度：goals model 已建（范本），其余按 Story1→9 推进。
