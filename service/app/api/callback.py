"""OpenCode 回调路由（/api/callback/opencode/*）。

doc/04 §3.12：
  POST /api/callback/opencode/output    OpenCode 产出回调 -> 记录产出 + 发验收卡片 + 发送文件
  POST /api/callback/opencode/timeout   Redis 超时告警回调 -> 飞书通知

路径前缀 /api/callback（不带 v1），在 main.py 单独挂载。
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.common import ApiResponse
from app.schemas.task import (
    OpencodeOutputCallbackRequest,
    OpencodeTimeoutCallbackRequest,
    RecordOutputData,
    TimeoutAlertData,
)
from app.services.task_app_svc import TaskAppSvc

router = APIRouter()

DBSession = Annotated[Session, Depends(get_db)]


@router.post("/opencode/output", response_model=ApiResponse[RecordOutputData])
def opencode_output(
    payload: OpencodeOutputCallbackRequest, db: DBSession
) -> ApiResponse[RecordOutputData]:
    """OpenCode 产出回调。记录 workspace_progress + DEL 超时 + 发验收卡片 + 发送文件。"""
    outputs = [o.model_dump() for o in payload.outputs]
    data = TaskAppSvc(db).record_output(payload.task_id, payload.workspace_id, outputs)
    return ApiResponse(data=data)


@router.post("/opencode/timeout", response_model=ApiResponse[TimeoutAlertData])
def opencode_timeout(
    payload: OpencodeTimeoutCallbackRequest, db: DBSession
) -> ApiResponse[TimeoutAlertData]:
    """Redis 超时告警回调（KeyExpirationEvent 触发）。飞书通知。"""
    data = TaskAppSvc(db).handle_timeout(payload.task_id, payload.workspace_id)
    return ApiResponse(data=data)
