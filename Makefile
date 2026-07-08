.PHONY: install dev test migrate upgrade lint format h5-dev h5-build up down

SERVICE_DIR := service
H5_DIR := h5

# 一次性安装所有依赖
install:
	cd $(SERVICE_DIR) && uv sync
	cd $(H5_DIR) && npm install

# 本地开发：起 Service（:8001）
dev:
	cd $(SERVICE_DIR) && uv run uvicorn app.main:app --reload --port 8001

# 跑测试
test:
	cd $(SERVICE_DIR) && uv run pytest -v

# 生成迁移：make migrate MSG="add themes phases tasks"
migrate:
	cd $(SERVICE_DIR) && uv run alembic revision --autogenerate -m "$(MSG)"

# 应用迁移到最新
upgrade:
	cd $(SERVICE_DIR) && uv run alembic upgrade head

lint:
	cd $(SERVICE_DIR) && uv run ruff check .
	cd $(SERVICE_DIR) && uv run ruff format --check .

format:
	cd $(SERVICE_DIR) && uv run ruff format .

# H5
h5-dev:
	cd $(H5_DIR) && npm run dev

h5-build:
	cd $(H5_DIR) && npm run build

# Docker
up:
	docker compose up -d --build

down:
	docker compose down
