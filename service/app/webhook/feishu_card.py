"""飞书卡片回调入口（入口 B）。

飞书 3 秒超时：回调仅做 DB 写 + 即时级联（<200ms）后立即返回；
耗时操作（工作空间初始化、opencode 执行、刷卡片、写 daily.md）事务提交后异步（BackgroundTasks）。

action_id 硬编码路由（doc/06）：
  schedule.confirm       -> ScheduleAppSvc.confirm（S2：多选专题+managed/path+deadline）
  story3_确认今日计划     -> DailyAppSvc.confirm（S3：任务勾选+前置勾选 -> INSERT 3 表）
  story4B_确认后置       -> TaskAppSvc.post_confirm（S4B：INSERT 后置 + 异步执行）
  story4B_不需要后置     -> TaskAppSvc.post_confirm（S4B：全取消，不插入后置）
  story4A_验收通过       -> TaskAppSvc.output_confirm（S4A：验收通过 -> 标记完成+即时级联）
  story4A_需要修改       -> TaskAppSvc.output_reject（S4A：重试/通知）
  story5_标记完成        -> TaskAppSvc.patch_status（S5：异议 forward，即时级联+异步刷卡片）
  story5_标记未完成      -> TaskAppSvc.patch_status（S5：异议 revert，系统填 reason+异步刷卡片）
  story5_确认日终总结    -> DailyAppSvc.confirm_summary（S5：标记 is_confirmed+异步写 daily.md）
  story6_已阅周总结      -> WeeklyAppSvc.confirm_summary（S6：标记 is_confirmed+异步写 weekly.md）
  story8_确认激活        -> ScheduleAppSvc.activate（S8：阶段衔接激活+即时级联+异步工作空间初始化）
  story8_暂不激活        -> 记录（no-op，24h 后巡检再提醒）
  story8_去激活          -> 返回 Story2 激活链接（跳转，非事务）
  story8_去页面调整       -> 返回 H5 链接（跳转，非事务）
其余 action_id 保留 TODO，由后续 Story 实现。
"""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.common import ApiResponse
from app.schemas.daily import DailyConfirmRequest
from app.schemas.schedule import ScheduleActivateRequest, ScheduleConfirmRequest
from app.schemas.task import PostConfirmWebhookRequest
from app.services.daily_app_svc import DailyAppSvc
from app.services.schedule_app_svc import ScheduleAppSvc
from app.services.task_app_svc import TaskAppSvc
from app.services.weekly_app_svc import WeeklyAppSvc
from app.services.workspace_app_svc import WorkspaceAppSvc

router = APIRouter()

DBSession = Annotated[Session, Depends(get_db)]


@router.post("/feishu/card")
async def feishu_card_callback(
    request: Request,
    background_tasks: BackgroundTasks,
    db: DBSession,
) -> dict:
    """飞书卡片按钮回调。解析 action.value.action_id -> 路由到对应 AppService。

    飞书配置回调地址时会先发 url_verification 验签请求，要求原样返回 challenge
    （飞书据此确认地址归属）。此请求无 action 字段，须在 action 路由前优先处理。
    """
    payload = await request.json()

    # 飞书验签：type=url_verification 时原样回 challenge（飞书回调验签约定）
    if payload.get("type") == "url_verification":
        return {"challenge": payload.get("challenge", "")}

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

    # ---- Story5: 日终总结异议 + 确认 ----

    if action_id in ("story5_标记完成", "story5_标记未完成"):
        task_id = action_value.get("task_id")
        message_id = action_value.get("message_id", "")
        daily_id = action_value.get("daily_id", "")
        if not task_id:
            return {"code": 1002, "message": "回调缺少 task_id", "data": None}
        target_status = "已完成" if action_id == "story5_标记完成" else "待执行"
        # 事务内：DB 写 + 即时级联（<200ms）；立即返回
        data = TaskAppSvc(db).patch_status(task_id, target_status, triggered_by="user")
        # 事务后异步：刷新卡片（message_id 调 feishu update_card，3 秒超时内不阻塞）
        background_tasks.add_task(
            TaskAppSvc.refresh_summary_card_async, task_id, message_id, daily_id
        )
        return ApiResponse(data=data).model_dump()

    if action_id == "story5_确认日终总结":
        daily_id = action_value.get("daily_id")
        if not daily_id:
            return {"code": 1002, "message": "回调缺少 daily_id", "data": None}
        # 事务内：UPDATE is_confirmed + COMMIT（<200ms）；立即返回
        data = DailyAppSvc(db).confirm_summary(daily_id)
        # 事务后异步：写 daily.md 快照（3 秒超时内不阻塞）
        background_tasks.add_task(DailyAppSvc.write_daily_md_async, daily_id)
        return ApiResponse(data=data).model_dump()

    # ---- Story6: 周总结确认（"已阅"归档，不级联）----

    if action_id == "story6_已阅周总结":
        week = action_value.get("week")
        if not week:
            return {"code": 1002, "message": "回调缺少 week", "data": None}
        # 事务内：INSERT/UPDATE weekly_records is_confirmed + COMMIT（<200ms）；立即返回
        data = WeeklyAppSvc(db).confirm_summary(week)
        # 事务后异步：写 weekly.md 快照（3 秒超时内不阻塞）
        background_tasks.add_task(WeeklyAppSvc.write_weekly_md_async, week)
        return ApiResponse(data=data).model_dump()

    # ---- Story8: 主动巡检与阶段衔接 ----

    if action_id == "story8_确认激活":
        try:
            req = ScheduleActivateRequest.model_validate(action_value)
        except ValidationError as e:
            return {"code": 1002, "message": f"回调参数不合法: {e}", "data": None}
        # 事务内：UPDATE phase + 即时级联 + audit(forward,supervisor) + COMMIT（<200ms）
        data = ScheduleAppSvc(db).activate(req.phase_id, req.deadline, req.user_id)
        # 事务后异步：managed=1 工作空间初始化（3 秒超时内不阻塞）
        if data.workspace_managed and data.workspace_status == "未初始化":
            background_tasks.add_task(WorkspaceAppSvc.init, data.workspace_id)
        return ApiResponse(data=data).model_dump()

    if action_id == "story8_暂不激活":
        # 记录：不激活，24h 后巡检再提醒（doc/06 表2 story8_暂不激活）
        phase_id = action_value.get("phase_id", "")
        import logging

        logging.getLogger(__name__).info(
            "story8_暂不激活: phase=%s 用户选择暂不激活，24h 后巡检再提醒", phase_id
        )
        return {"code": 0, "message": "已记录，24h 后再提醒", "data": {"phase_id": phase_id}}

    if action_id == "story8_去激活":
        # 跳转：返回 Story2 激活链接（H5/卡片），非执行态事务
        goal_id = action_value.get("goal_id", "")
        theme_id = action_value.get("theme_id", "")
        from app.config import settings

        link = f"{settings.h5_base_url}/schedule?goal_id={goal_id}&theme_id={theme_id}"
        return {"code": 0, "message": "请前往页面激活", "data": {"link": link}}

    if action_id == "story8_去页面调整":
        # 跳转：返回 H5 看板链接，非执行态事务
        phase_id = action_value.get("phase_id", "")
        from app.config import settings

        link = f"{settings.h5_base_url}/board?phase_id={phase_id}"
        return {"code": 0, "message": "请前往页面调整", "data": {"link": link}}

    return {"code": 0, "message": "noop", "data": None}
