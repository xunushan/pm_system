"""飞书卡片回调入口（入口 B）。

飞书 3 秒超时：回调仅做 DB 写 + 即时级联（<200ms）后立即返回；
耗时操作（工作空间初始化）事务提交后异步（BackgroundTasks）。

action_id 硬编码路由（doc/06 表2）：
  schedule.confirm -> ScheduleAppSvc.confirm（多选专题+managed/path+deadline）
其余 action_id 保留 TODO，由后续 Story 实现。
"""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.common import ApiResponse
from app.schemas.schedule import ScheduleConfirmRequest
from app.services.schedule_app_svc import ScheduleAppSvc
from app.services.workspace_app_svc import WorkspaceAppSvc

router = APIRouter()

DBSession = Annotated[Session, Depends(get_db)]


@router.post("/feishu/card")
async def feishu_card_callback(
    request: Request,
    background_tasks: BackgroundTasks,
    db: DBSession,
) -> dict:
    """飞书卡片按钮回调。解析 action.value.action_id -> 路由到对应 AppService。"""
    payload = await request.json()
    action_value = (payload.get("action") or {}).get("value", {})
    action_id = action_value.get("action_id")

    if action_id == "schedule.confirm":
        try:
            req = ScheduleConfirmRequest.model_validate(action_value)
        except ValidationError as e:
            return {"code": 1002, "message": f"回调参数不合法: {e}", "data": None}
        data = ScheduleAppSvc(db).confirm(req.user_id, req.goal_id, req.items)
        # 事务后异步：managed=1 工作空间初始化（3 秒超时内不阻塞）
        for ap in data.activated_phases:
            if ap.workspace_managed:
                background_tasks.add_task(WorkspaceAppSvc.init, ap.workspace_id)
        return ApiResponse(data=data).model_dump()

    # 其余 action_id 保留 TODO（plan.confirm 在 Story1 已实现？此处不重复）
    return {"code": 0, "message": "noop", "data": None}
