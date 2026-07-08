"""FastAPI 应用入口。

挂载：
  - /api/v1/*        REST API（Skill + H5 页面调用）
  - /webhook/feishu/card  飞书卡片回调（入口 B）
  - /health          健康检查
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1.router import api_router
from app.webhook.feishu_card import router as webhook_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # TODO(Story8): 启动 Supervisor 定时巡检（APScheduler）
    #   if settings.supervisor_enabled:
    #       from app.supervisor.scheduler import start_scheduler
    #       start_scheduler()
    yield
    # TODO(Story8): 关闭 Scheduler


app = FastAPI(title="目标管理系统 Service", version="0.1.0", lifespan=lifespan)


@app.get("/health", tags=["meta"])
def health() -> dict:
    return {"status": "ok"}


app.include_router(api_router, prefix="/api/v1")
app.include_router(webhook_router, prefix="/webhook")
