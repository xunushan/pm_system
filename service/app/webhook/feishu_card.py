"""飞书卡片回调入口（入口 B）。schema 2.0 双路由（doc/09 V8）。

回调取法（doc/09 V2 完整路径，修正 FIX-1 错误取顶层）::

    event = payload["event"]
    message_id = event["context"]["open_message_id"]   # 刷新用
    action_value = event["action"].get("value", {})     # form 外按钮自定义回传
    form_value = event["action"].get("form_value", {})  # form 内组件输入值
    btn_name = event["action"].get("name", "")           # 区分 form_submit 按钮
    action_id = action_value.get("action_id")             # 仅 form 外按钮有

双路由（doc/09 V8）：
  - form 外按钮（有 action_id）：按 action_id 路由
  - form 内按钮（无 action_id，有 btn_name）：按 btn_name 路由

飞书 3 秒超时（铁律 §3#4）：回调仅做 DB 写 + 即时级联（<200ms）后立即返回；
耗时操作（工作空间初始化、opencode 执行、刷卡片、写 daily.md）事务提交后异步（BackgroundTasks）。

注意：schema 2.0 下部分原 action_id 按钮已改为 form_submit（靠 name 路由），
对应旧 action_id 分支保留过渡（取法已适配到 event.action.value），其 form_value
业务逻辑（checker/date_picker 解析）归 PR-D 全回调 update_card 补全。
"""

import logging
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.card_registry import get_card_context
from app.db.session import get_db
from app.schemas.common import ApiResponse
from app.schemas.daily import DailyConfirmRequest
from app.schemas.schedule import ScheduleActivateRequest, ScheduleConfirmRequest
from app.schemas.task import PostConfirmWebhookRequest
from app.services.daily_app_svc import DailyAppSvc
from app.services.plan_app_svc import PlanAppSvc
from app.services.schedule_app_svc import ScheduleAppSvc
from app.services.task_app_svc import TaskAppSvc
from app.services.weekly_app_svc import WeeklyAppSvc
from app.services.workspace_app_svc import WorkspaceAppSvc

logger = logging.getLogger(__name__)

router = APIRouter()

DBSession = Annotated[Session, Depends(get_db)]


@router.post("/feishu/card")
async def feishu_card_callback(
    request: Request,
    background_tasks: BackgroundTasks,
    db: DBSession,
) -> dict:
    """飞书卡片按钮回调。schema 2.0 双路由（doc/09 V8）。

    飞书配置回调地址时会先发 url_verification 验签请求，要求原样返回 challenge
    （飞书据此确认地址归属）。此请求无 event 字段，须在路由解析前优先处理。
    """
    payload = await request.json()

    # 飞书验签：type=url_verification 时原样回 challenge（飞书回调验签约定）
    if payload.get("type") == "url_verification":
        return {"challenge": payload.get("challenge", "")}

    # ---- schema 2.0 回调结构解析（doc/09 V2）----
    event = payload.get("event")
    if not event:
        # 非 schema 2.0 卡片回调（无 event 字段），noop
        return {"code": 0, "message": "noop", "data": None}

    action = event.get("action", {})
    # message_id 从 event.context.open_message_id 取（doc/09 V2，修正 FIX-1 错误取顶层）
    message_id = event.get("context", {}).get("open_message_id", "")
    action_value = action.get("value", {})  # form 外按钮自定义回传
    form_value = action.get("form_value", {})  # form 内组件输入值
    btn_name = action.get("name", "")  # 区分 form_submit 按钮
    action_id = action_value.get("action_id")  # 仅 form 外按钮有

    # ===== form 外按钮路由（有 action_id，doc/09 V8）=====

    if action_id == "story1_确认方案":
        # S1 确认方案（form 外，doc/09 §S1 确认前 -> 点确认方案后）
        # 回传 draft_id，Service 读 draft -> 建 goal/theme/phase/task -> 删 draft
        draft_id = action_value.get("draft_id")
        if not draft_id:
            return {"code": 1002, "message": "回调缺少 draft_id", "data": None}
        data = PlanAppSvc(db).confirm(draft_id)
        # update_card 刷已确认态归 PR-D（全回调 update_card 补全）
        return ApiResponse(data=data).model_dump()

    if action_id == "schedule.confirm":
        # S2 确认调度（旧 action_id 路由，取法适配到 event.action.value）。
        # schema 2.0 下确认调度按钮是 form_submit（name=confirm_btn，卡片 B），
        # date_picker form_value 业务解析归 PR-D。本分支保留过渡。
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
        # S3 确认今日计划（旧 action_id 路由，取法适配）。
        # schema 2.0 下确认按钮是 form_submit（name=confirm_btn），checker
        # form_value 业务解析归 PR-D。本分支保留过渡。
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
        # S4B 后置确认（旧 action_id 路由，取法适配）。
        # schema 2.0 下确认按钮是 form_submit（name=confirm_btn），checker
        # form_value 业务解析归 PR-D。本分支保留过渡。
        try:
            req = PostConfirmWebhookRequest.model_validate(action_value)
        except ValidationError as e:
            return {"code": 1002, "message": f"回调参数不合法: {e}", "data": None}
        data = TaskAppSvc(db).post_confirm(req.task_id, req.user_id, req.post_subtasks)
        # 事务后异步：opencode run 执行后置（3 秒超时内不阻塞）
        if data.async_triggered:
            background_tasks.add_task(TaskAppSvc.trigger_post_async, req.task_id)
        return ApiResponse(data=data).model_dump()

    if action_id == "story4A_验收通过":
        # S4A 验收通过（旧 action_id 路由，取法适配）。
        # schema 2.0 下是 form_submit（name=btn_pass），form_value 业务归 PR-D。
        task_id = action_value.get("task_id")
        user_id = action_value.get("user_id", "feishu_user")
        wp_ids = action_value.get("workspace_progress_ids", [])
        if not task_id:
            return {"code": 1002, "message": "回调缺少 task_id", "data": None}
        data = TaskAppSvc(db).output_confirm(task_id, user_id, wp_ids)
        return ApiResponse(data=data).model_dump()

    if action_id == "story4A_需要修改":
        # S4A 需要修改（旧 action_id 路由，取法适配）。
        # schema 2.0 下是 form_submit（name=btn_reject），form_value.feedback
        # 业务解析归 PR-D。
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
        # S5 日终异议（旧 action_id 路由，取法适配 + message_id 修正到 event.context）。
        # schema 2.0 下日终确认是 form_submit（name=confirm_btn）+ checker，
        # 本分支保留过渡，form_value 业务归 PR-D。
        task_id = action_value.get("task_id")
        daily_id = action_value.get("daily_id", "")
        if not task_id:
            return {"code": 1002, "message": "回调缺少 task_id", "data": None}
        target_status = "已完成" if action_id == "story5_标记完成" else "待执行"
        # 事务内：DB 写 + 即时级联（<200ms）；立即返回
        data = TaskAppSvc(db).patch_status(task_id, target_status, triggered_by="user")
        # 事务后异步：刷新卡片（message_id 从 event.context.open_message_id 取，doc/09 V2）
        background_tasks.add_task(
            TaskAppSvc.refresh_summary_card_async, task_id, message_id, daily_id
        )
        return ApiResponse(data=data).model_dump()

    if action_id == "story5_确认日终总结":
        # S5 确认日终总结（旧 action_id 路由，取法适配）。
        # schema 2.0 下是 form_submit（name=confirm_btn），daily_id 靠 message_id
        # 反查 card_registry（P2 路由缺口），归 PR-D。本分支保留过渡。
        daily_id = action_value.get("daily_id")
        if not daily_id:
            return {"code": 1002, "message": "回调缺少 daily_id", "data": None}
        # 事务内：UPDATE is_confirmed + COMMIT（<200ms）；立即返回
        data = DailyAppSvc(db).confirm_summary(daily_id)
        # 事务后异步：写 daily.md 快照（3 秒超时内不阻塞）
        background_tasks.add_task(DailyAppSvc.write_daily_md_async, daily_id)
        return ApiResponse(data=data).model_dump()

    # ---- Story6: 周总结确认（form 外，仍是 action_id 路由）----

    if action_id == "story6_已阅周总结":
        # S6 周总结已阅（form 外，doc/09 §S6）：action_id + week 回传
        week = action_value.get("week")
        if not week:
            return {"code": 1002, "message": "回调缺少 week", "data": None}
        # 事务内：INSERT/UPDATE weekly_records is_confirmed + COMMIT（<200ms）；立即返回
        data = WeeklyAppSvc(db).confirm_summary(week)
        # 事务后异步：写 weekly.md 快照（3 秒超时内不阻塞）
        background_tasks.add_task(WeeklyAppSvc.write_weekly_md_async, week)
        return ApiResponse(data=data).model_dump()

    # ---- Story8: 阶段衔接 + 巡检跳转 ----

    if action_id == "story8_确认激活":
        # S8 确认激活（旧 action_id 路由，取法适配）。
        # schema 2.0 下是 form_submit（name=btn_activate），date_picker
        # form_value 业务解析归 PR-D。本分支保留过渡。
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
        # S8 暂不激活（旧 action_id 路由，取法适配）。
        # schema 2.0 下是 form_submit（name=btn_defer），归 PR-D。本分支保留过渡。
        # 记录：不激活，24h 后巡检再提醒（doc/06 表2 story8_暂不激活）
        phase_id = action_value.get("phase_id", "")
        logger.info("story8_暂不激活: phase=%s 用户选择暂不激活，24h 后巡检再提醒", phase_id)
        return {"code": 0, "message": "已记录，24h 后再提醒", "data": {"phase_id": phase_id}}

    if action_id == "story8_去激活":
        # S8 去激活（form 外，build_theme_completed_card / build_start_date_reminder_card）
        # 跳转：返回 Story2 激活链接（H5/卡片），非执行态事务
        goal_id = action_value.get("goal_id", "")
        theme_id = action_value.get("theme_id", "")
        from app.config import settings

        link = f"{settings.h5_base_url}/schedule?goal_id={goal_id}&theme_id={theme_id}"
        return {"code": 0, "message": "请前往页面激活", "data": {"link": link}}

    if action_id == "story8_去页面调整":
        # S8 去页面调整（form 外，build_deadline_reminder_card）
        # 跳转：返回 H5 看板链接，非执行态事务
        phase_id = action_value.get("phase_id", "")
        from app.config import settings

        link = f"{settings.h5_base_url}/board?phase_id={phase_id}"
        return {"code": 0, "message": "请前往页面调整", "data": {"link": link}}

    # ===== form 内按钮路由（有 btn_name，无 action_id，doc/09 V8）=====

    if btn_name == "next_btn":
        # S2 下一步（form_submit，doc/09 §S2 状态1->2）
        # 从 form_value 取勾选的 themes（checker name=theme_<id>，值 bool，doc/09 V7）
        selected_theme_ids = [
            k.replace("theme_", "") for k, v in form_value.items() if k.startswith("theme_") and v
        ]
        if not selected_theme_ids:
            return {"code": 1002, "message": "未勾选任何专题", "data": None}
        # message_id 反查 goal_id（P2 路由缺口，card_registry）
        ctx = get_card_context(message_id)
        goal_id = (ctx or {}).get("goal_id", "")
        # 事务后异步：update_card patch 卡片 A -> B（build_schedule_card_b，传选中 phases）
        background_tasks.add_task(
            ScheduleAppSvc.patch_to_card_b_async, message_id, selected_theme_ids, goal_id
        )
        return {"code": 0, "message": "正在生成卡片 B", "data": {"goal_id": goal_id}}

    # 其他 form_submit 按钮（confirm_btn/btn_pass/btn_reject/btn_activate/btn_defer）
    # 的 form_value 业务处理（checker 反转 / date_picker 解析 / reassign 互斥 / delete_session）
    # 归 PR-D（全回调 update_card 补全 + form_value 处理）。收到未知 btn_name 时 noop。

    return {"code": 0, "message": "noop", "data": None}
