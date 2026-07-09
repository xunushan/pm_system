"""飞书卡片回调入口（入口 B）。

飞书 3 秒超时：回调仅做 DB 写 + 即时级联（<200ms）后立即返回；
耗时操作（工作空间初始化、opencode 执行）事务提交后异步（BackgroundTasks）。

action_id 硬编码路由（doc/06）：
  schedule.confirm       -> ScheduleAppSvc.confirm（S2：多选专题+managed/path+deadline）
  story3_确认今日计划     -> DailyAppSvc.confirm（S3：任务勾选+前置勾选 -> INSERT 3 表）
  story4B_确认后置       -> TaskAppSvc.post_confirm（S4B：INSERT 后置 + 异步执行）
  story4B_不需要后置     -> TaskAppSvc.post_confirm（S4B：全取消，不插入后置）
  story4A_验收通过       -> TaskAppSvc.output_confirm（S4A：验收通过 -> 标记完成+即时级联）
  story4A_需要修改       -> TaskAppSvc.output_reject（S4A：重试/通知）
其余 action_id 保留 TODO，由后续 Story 实现。
"""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.common import ApiResponse
from app.schemas.daily import DailyConfirmRequest
from app.schemas.schedule import ScheduleConfirmRequest
from app.schemas.task import PostConfirmWebhookRequest
from app.services.daily_app_svc import DailyAppSvc
from app.services.schedule_app_svc import ScheduleAppSvc
from app.services.task_app_svc import TaskAppSvc
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

    if action_id == "story3_确认今日计划":
        try:
            req = DailyConfirmRequest.model_validate(action_value)
        except ValidationError as e:
            return {"code": 1002, "message": f"回调参数不合法: {e}", "data": None}
        data = DailyAppSvc(db).confirm(
            user_id=req.user_id,
            date_=req.date,
            task_ids=req.task_ids,
            pre_subtasks=req.pre_subtasks,
            push_source=req.push_source,
        )
        # 事务后异步：opencode 执行前置 + 启动智能体 serve（3 秒超时内不阻塞）
        if data.async_triggered:
            background_tasks.add_task(DailyAppSvc.trigger_async, data.daily_id)
        return ApiResponse(data=data).model_dump()

    if action_id in ("story4B_确认后置", "story4B_不需要后置"):
        try:
            req = PostConfirmWebhookRequest.model_validate(action_value)
        except ValidationError as e:
            return {"code": 1002, "message": f"回调参数不合法: {e}", "data": None}
        data = TaskAppSvc(db).post_confirm(req.task_id, req.user_id, req.post_subtasks)
        # 事务后异步：opencode run 执行后置（3 秒超时内不阻塞）
        if data.async_triggered:
            background_tasks.add_task(TaskAppSvc.trigger_post_async, req.task_id)
        return ApiResponse(data=data).model_dump()

    # 其余 action_id 保留 TODO（plan.confirm 走 plans/confirm API，不在此路由）

    if action_id == "story4A_验收通过":
        task_id = action_value.get("task_id")
        user_id = action_value.get("user_id", "feishu_user")
        wp_ids = action_value.get("workspace_progress_ids", [])
        if not task_id:
            return {"code": 1002, "message": "回调缺少 task_id", "data": None}
        data = TaskAppSvc(db).output_confirm(task_id, user_id, wp_ids)
        return ApiResponse(data=data).model_dump()

    if action_id == "story4A_需要修改":
        task_id = action_value.get("task_id")
        user_id = action_value.get("user_id", "feishu_user")
        feedback = action_value.get("feedback", "")
        if not task_id:
            return {"code": 1002, "message": "回调缺少 task_id", "data": None}
        data = TaskAppSvc(db).output_reject(task_id, user_id, feedback)
        # 事务后异步：retry 的 dispatch_task + Redis / manual_intervention 的 shutdown + 通知
        background_tasks.add_task(TaskAppSvc.trigger_reject_async, task_id, feedback)
        return ApiResponse(data=data).model_dump()

    return {"code": 0, "message": "noop", "data": None}
