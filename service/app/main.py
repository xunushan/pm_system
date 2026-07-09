"""FastAPI 应用入口。

挂载：
  - /api/v1/*                  REST API（Skill + H5 页面调用）
  - /api/callback/opencode/*   OpenCode 回调（产出/超时，doc/04 §3.12）
  - /webhook/feishu/card       飞书卡片回调（入口 B）
  - /health                    健康检查
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.callback import router as callback_router
from app.api.v1.router import api_router
from app.core.exceptions import AppError
from app.schemas.common import ApiResponse
from app.webhook.feishu_card import router as webhook_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动 Supervisor：事件总线 dispatcher + 定时巡检 scheduler（Story8）
    from app.config import settings
    from app.supervisor.event_bus import start_dispatcher, stop_dispatcher
    from app.supervisor.scheduler import start_scheduler, stop_scheduler

    start_dispatcher()
    if settings.supervisor_enabled:
        start_scheduler()
    yield
    # 关闭 Supervisor
    stop_scheduler()
    stop_dispatcher()


app = FastAPI(title="目标管理系统 Service", version="0.1.0", lifespan=lifespan)


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:  # noqa: ARG001
    """业务异常 -> 统一错误响应 {code, message, data: null}（doc/04 2.2/2.3）。"""
    return JSONResponse(
        status_code=exc.http_status,
        content=ApiResponse(code=exc.code, message=exc.message, data=None).model_dump(),
    )


@app.get("/health", tags=["meta"])
def health() -> dict:
    return {"status": "ok"}


app.include_router(api_router, prefix="/api/v1")
app.include_router(callback_router, prefix="/api/callback")
app.include_router(webhook_router, prefix="/webhook")
