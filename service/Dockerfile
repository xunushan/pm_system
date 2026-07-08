# Service Docker 镜像。基于 uv 官方镜像，分层缓存依赖。
# 详见 https://docs.astral.sh/uv/guides/integration/docker/
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app

# 依赖（先拷依赖文件，利用层缓存）
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# 业务代码 + 迁移
COPY app/ ./app/
COPY alembic.ini alembic/ ./

# 安装项目本身
RUN uv sync --frozen --no-dev

ENV DATABASE_URL=sqlite:///app/data/pm.db

EXPOSE 8001
# 启动：先跑迁移，再起 uvicorn
CMD ["sh", "-c", "uv run alembic upgrade head && uv run uvicorn app.main:app --host 0.0.0.0 --port 8001"]
