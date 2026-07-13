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

form_submit 按钮无 task_id/daily_id 等业务 ID（doc/09 V1），靠 message_id 反查
card_registry（PR-C 落地）。confirm_btn 在多张卡片复用，靠 card_registry type 分发。

飞书 3 秒超时（铁律 §3#4）：回调仅做 DB 写 + 即时级联（<200ms）后立即返回；
卡片刷新在回调响应体同步返回（方案 B：card.data 传终态卡片 JSON，飞书立即更新）；
耗时副作用（工作空间初始化、opencode 执行、写 daily.md/weekly.md）
事务提交后异步（BackgroundTasks）。
"""

import logging
from datetime import date
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from sqlalchemy.orm import Session

from app.core.card_registry import get_card_context, set_card_context
from app.db.session import get_db
from app.schemas.common import ApiResponse
from app.schemas.daily import PreSubtaskInput
from app.schemas.schedule import ScheduleItem
from app.schemas.task import PostSubtaskInput
from app.services.daily_app_svc import DailyAppSvc
from app.services.plan_app_svc import PlanAppSvc
from app.services.schedule_app_svc import ScheduleAppSvc
from app.services.task_app_svc import TaskAppSvc
from app.services.weekly_app_svc import WeeklyAppSvc
from app.services.workspace_app_svc import WorkspaceAppSvc

logger = logging.getLogger(__name__)

router = APIRouter()

DBSession = Annotated[Session, Depends(get_db)]

_DEFAULT_USER_ID = "feishu_user"


# ---- form_value 解析辅助（doc/09 V7 类型）----


def _extract_checked_ids(form_value: dict, prefix: str) -> list[str]:
    """从 checker form_value 提取勾选（True）的 ID 列表。

    doc/09 V7：checker 值是 bool，key 是组件 name。
    如 form_value={"task_abc": true, "task_def": false}，prefix="task_" -> ["abc"]。
    """
    return [k[len(prefix) :] for k, v in form_value.items() if k.startswith(prefix) and v]


def _parse_date_picker_value(value: str | None) -> date | None:
    """解析 date_picker 值（doc/09 V7）。

    date_picker 值格式："2026-07-15 +0800"（含时区），取空格前的日期部分。
    """
    if not value:
        return None
    date_str = value.split(" ")[0]
    try:
        return date.fromisoformat(date_str)
    except ValueError:
        logger.warning("date_picker 值解析失败: %s", value)
        return None


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
        # 同步返回终态卡片（方案 B）：绿色已确认态（doc/09 §S1 确认后）
        card = PlanAppSvc.build_overview_done_card(
            data.goal_name,
            data.themes_created,
            data.phases_created,
            data.tasks_created,
            data.h5_url,
        )
        return {
            "toast": {"type": "success", "content": "方案已确认"},
            "card": {"type": "raw", "data": card},
        }

    if action_id == "story6_已阅周总结":
        # S6 周总结已阅（form 外，doc/09 §S6）：action_id + week 回传
        week = action_value.get("week")
        if not week:
            return {"code": 1002, "message": "回调缺少 week", "data": None}
        # 事务内：INSERT/UPDATE weekly_records is_confirmed + COMMIT（<200ms）；立即返回
        data = WeeklyAppSvc(db).confirm_summary(week)
        # 事务后异步：写 weekly.md 快照（3 秒超时内不阻塞）
        background_tasks.add_task(WeeklyAppSvc.write_weekly_md_async, week)
        # 同步返回终态卡片（方案 B）：绿色已阅态（doc/09 §S6 状态2）
        card = WeeklyAppSvc.build_weekly_done_card_from_db(db, week)
        return {
            "toast": {"type": "success", "content": "已阅"},
            "card": {"type": "raw", "data": card},
        }

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

    # ---- S4B 全选/全不选（form 外按钮，doc/09 §S4B）----
    # 点击不提交 form，Service update_card 刷新所有 checker checked 状态（保留按钮）

    if action_id == "story4B_全选":
        # 全选：同步返回刷新所有 checker checked=true（doc/09 §S4B"用户点全选后"）
        task_id = action_value.get("task_id", "")
        ctx = get_card_context(message_id)
        post_subtasks = (ctx or {}).get("post_subtasks", [])
        card = TaskAppSvc.build_post_confirm_toggle_card_from_db(db, task_id, post_subtasks, True)
        return {
            "toast": {"type": "success", "content": "已全选"},
            "card": {"type": "raw", "data": card},
        }

    if action_id == "story4B_全不选":
        # 全不选：同步返回刷新所有 checker checked=false（doc/09 §S4B"用户点全不选后"）
        task_id = action_value.get("task_id", "")
        ctx = get_card_context(message_id)
        post_subtasks = (ctx or {}).get("post_subtasks", [])
        card = TaskAppSvc.build_post_confirm_toggle_card_from_db(db, task_id, post_subtasks, False)
        return {
            "toast": {"type": "success", "content": "已全不选"},
            "card": {"type": "raw", "data": card},
        }

    # ===== form 内按钮路由（有 btn_name，无 action_id，doc/09 V8）=====

    if btn_name == "next_btn":
        # S2 下一步（form_submit，doc/09 §S2 状态1->2）
        # 从 form_value 取勾选的 themes（checker name=theme_<id>，值 bool，doc/09 V7）
        selected_theme_ids = _extract_checked_ids(form_value, "theme_")
        if not selected_theme_ids:
            return {"code": 1002, "message": "未勾选任何专题", "data": None}
        # message_id 反查 goal_id（P2 路由缺口，card_registry）
        ctx = get_card_context(message_id)
        goal_id = (ctx or {}).get("goal_id", "")
        # 同步返回卡片 B（方案 B）：查选中专题的第1个未开始阶段 -> build_schedule_card_b
        card = ScheduleAppSvc.build_schedule_card_b_from_db(db, selected_theme_ids, goal_id)
        if card is None:
            return {"code": 1002, "message": "选中专题无可激活阶段", "data": None}
        # 更新 card_registry 类型 schedule_a -> schedule_b（供 confirm_btn 回调区分）
        set_card_context(message_id, {"type": "schedule_b", "goal_id": goal_id})
        return {
            "toast": {"type": "info", "content": "请填 deadline"},
            "card": {"type": "raw", "data": card},
        }

    # ---- S4A 验收卡：btn_pass / btn_reject（doc/09 §S4A 场景1）----

    if btn_name == "btn_pass":
        # S4A 验收通过（form_submit，doc/09 §S4A 场景1->2）
        # task_id 靠 message_id 反查 card_registry（推卡时存 verification 上下文）
        ctx = get_card_context(message_id)
        if not ctx or "task_id" not in ctx:
            logger.warning("btn_pass: 无法反查 task_id, message_id=%s", message_id)
            return {"code": 1002, "message": "无法定位任务（message_id 未注册）", "data": None}
        task_id = ctx["task_id"]
        # 事务内：UPDATE task 已完成 + 即时级联 + 审计（<200ms）；立即返回
        data = TaskAppSvc(db).output_confirm(task_id, _DEFAULT_USER_ID, [])
        # 同步返回终态卡片（方案 B）：绿色验收通过态（doc/09 §S4A 场景1 点验收通过后）
        card = TaskAppSvc.build_verification_done_card_from_db(db, task_id, True)
        return {
            "toast": {"type": "success", "content": "验收通过"},
            "card": {"type": "raw", "data": card},
        }

    if btn_name == "btn_reject":
        # S4A 需要修改（form_submit，doc/09 §S4A 场景1->2）
        # 从 form_value 读 feedback（input name=feedback，值字符串，doc/09 V7 + issue#20）
        feedback = form_value.get("feedback", "")
        if not feedback:
            return {"code": 1002, "message": "请填写修改建议", "data": None}
        # task_id 靠 message_id 反查 card_registry
        ctx = get_card_context(message_id)
        if not ctx or "task_id" not in ctx:
            logger.warning("btn_reject: 无法反查 task_id, message_id=%s", message_id)
            return {"code": 1002, "message": "无法定位任务（message_id 未注册）", "data": None}
        task_id = ctx["task_id"]
        # 事务内：retry_count+=1（<200ms）；立即返回
        data = TaskAppSvc(db).output_reject(task_id, _DEFAULT_USER_ID, feedback)
        # 事务后异步：retry 的 dispatch_task + manual_intervention 的 delete_session（D26）
        background_tasks.add_task(TaskAppSvc.trigger_reject_async, task_id, feedback)
        # retry 路径：同步返回终态卡片（方案 B）：橙色反馈已下发态（doc/09 §S4A 场景2）
        # manual_intervention 路径（3 次不通过）推人工接手卡（不更新原卡），保持原逻辑
        if data.action == "retry":
            card = TaskAppSvc.build_verification_done_card_from_db(db, task_id, False, feedback)
            return {
                "toast": {"type": "success", "content": "已下发修改"},
                "card": {"type": "raw", "data": card},
            }
        return ApiResponse(data=data).model_dump()

    # ---- S8 衔接卡：btn_activate / btn_defer（doc/09 §S8）----

    if btn_name == "btn_activate":
        # S8 确认激活（form_submit，doc/09 §S8 状态1->2）
        # 从 form_value 解析 deadline（date_picker name=deadline，值"2026-07-25 +0800"，doc/09 V7）
        deadline = _parse_date_picker_value(form_value.get("deadline"))
        if deadline is None:
            return {"code": 1002, "message": "请选择 deadline", "data": None}
        # phase_id 靠 message_id 反查 card_registry
        ctx = get_card_context(message_id)
        if not ctx or "phase_id" not in ctx:
            logger.warning("btn_activate: 无法反查 phase_id, message_id=%s", message_id)
            return {"code": 1002, "message": "无法定位阶段（message_id 未注册）", "data": None}
        phase_id = ctx["phase_id"]
        # 事务内：UPDATE phase + 即时级联 + audit(forward,supervisor) + COMMIT（<200ms）
        data = ScheduleAppSvc(db).activate(phase_id, deadline, _DEFAULT_USER_ID)
        # 事务后异步：managed=1 工作空间初始化（3 秒超时内不阻塞）
        if data.workspace_managed and data.workspace_status == "未初始化":
            background_tasks.add_task(WorkspaceAppSvc.init, data.workspace_id)
        # 同步返回终态卡片（方案 B）：绿色已激活态（doc/09 §S8 状态2）
        card = ScheduleAppSvc.build_activate_done_card(
            data.name, data.deadline.isoformat() if data.deadline else ""
        )
        return {
            "toast": {"type": "success", "content": "已激活"},
            "card": {"type": "raw", "data": card},
        }

    if btn_name == "btn_defer":
        # S8 暂不激活（form_submit，doc/09 §S8 状态1->3）
        # phase_id 靠 message_id 反查 card_registry
        ctx = get_card_context(message_id)
        phase_id = (ctx or {}).get("phase_id", "")
        # 记录暂缓：不激活，24h 后巡检再提醒（doc/06 表2 story8_暂不激活）
        logger.info("btn_defer: phase=%s 用户选择暂不激活，24h 后巡检再提醒", phase_id)
        # 同步返回终态卡片（方案 B）：橙色暂缓态（doc/09 §S8 状态3）
        card = ScheduleAppSvc.build_defer_done_card_from_db(db, phase_id)
        return {
            "toast": {"type": "info", "content": "已暂缓"},
            "card": {"type": "raw", "data": card},
        }

    # ---- confirm_btn（多卡复用，靠 card_registry type 分发）----

    if btn_name == "confirm_btn":
        ctx = get_card_context(message_id)
        if not ctx:
            logger.warning("confirm_btn: 无法反查卡片上下文, message_id=%s", message_id)
            return {
                "code": 1002,
                "message": "无法定位卡片上下文（message_id 未注册）",
                "data": None,
            }
        card_type = ctx.get("type", "")

        # S2 卡片 B 确认调度（doc/09 §S2 状态2->3）
        if card_type == "schedule_b":
            goal_id = ctx.get("goal_id", "")
            # 从 form_value 解析每个选中专题的 deadline
            # date_picker name=dl_theme_<theme_id>，值"2026-07-15 +0800"（doc/09 V7）
            items: list[ScheduleItem] = []
            for k, v in form_value.items():
                if not k.startswith("dl_theme_"):
                    continue
                theme_id = k[len("dl_theme_") :]
                deadline = _parse_date_picker_value(v)
                if deadline is None:
                    return {
                        "code": 1002,
                        "message": f"专题 {theme_id} 的 deadline 格式无效",
                        "data": None,
                    }
                # managed 默认全托管（doc/09 §S2：默认全托管，调整 managed/path 走配置页）
                items.append(ScheduleItem(theme_id=theme_id, managed=True, deadline=deadline))
            if not items:
                return {"code": 1002, "message": "未解析到任何调度项", "data": None}
            # 事务内：激活各 phase + 即时级联 + 审计（<200ms）；立即返回
            data = ScheduleAppSvc(db).confirm(_DEFAULT_USER_ID, goal_id, items)
            # 事务后异步：managed=1 工作空间初始化（3 秒超时内不阻塞）
            for ap in data.activated_phases:
                if ap.workspace_managed:
                    background_tasks.add_task(WorkspaceAppSvc.init, ap.workspace_id)
            # 同步返回终态卡片（方案 B）：绿色已确认态（doc/09 §S2 状态3）
            activated = [
                {
                    "phase_id": ap.phase_id,
                    "name": ap.name,
                    "deadline": ap.deadline.isoformat() if ap.deadline else "",
                }
                for ap in data.activated_phases
            ]
            from app.config import settings

            h5_url = f"{settings.h5_base_url}/board?goal_id={goal_id}"
            card = ScheduleAppSvc.build_schedule_done_card_from_db(db, goal_id, activated, h5_url)
            return {
                "toast": {"type": "success", "content": "调度已确认"},
                "card": {"type": "raw", "data": card},
            }

        # S3 确认今日计划（doc/09 §S3 状态1->2）
        if card_type == "daily_plan":
            # 从 form_value 解析候选任务勾选（checker name=task_<id>，值 bool）
            task_ids = _extract_checked_ids(form_value, "task_")
            if not task_ids:
                return {"code": 1002, "message": "未勾选任何任务", "data": None}
            # 从 form_value 解析前置勾选（checker name=pre_<id>，值 bool）
            pre_ids = _extract_checked_ids(form_value, "pre_")
            # 前置名称从 card_registry context 查（推卡时存 prerequisites 映射）
            prereq_map = {p["id"]: p["name"] for p in ctx.get("prerequisites", [])}
            pre_subtasks = [
                PreSubtaskInput(name=prereq_map[pid]) for pid in pre_ids if pid in prereq_map
            ]
            # 日期从 card_registry context 查
            date_str = ctx.get("date")
            try:
                date_ = date.fromisoformat(date_str) if date_str else date.today()
            except ValueError:
                date_ = date.today()
            # 事务内：INSERT daily_records/daily_tasks/subtasks（<200ms）；立即返回
            data = DailyAppSvc(db).confirm(
                user_id=_DEFAULT_USER_ID,
                date_=date_,
                task_ids=task_ids,
                pre_subtasks=pre_subtasks,
                push_source="manual",
            )
            # 事务后异步：opencode 执行前置 + 启动智能体 serve（3 秒超时内不阻塞）
            if data.async_triggered:
                background_tasks.add_task(DailyAppSvc.trigger_async, data.daily_id)
            # 同步返回终态卡片（方案 B）：绿色已确认态（doc/09 §S3 状态2）
            card = DailyAppSvc.build_daily_plan_done_card_from_db(db, data.daily_id)
            if card is None:
                return {"code": 1002, "message": "daily 记录不存在", "data": None}
            return {
                "toast": {"type": "success", "content": "今日计划已确认"},
                "card": {"type": "raw", "data": card},
            }

        # S4B 确认后置（doc/09 §S4B 状态1->2）
        if card_type == "post_confirm":
            task_id = ctx.get("task_id", "")
            if not task_id:
                return {"code": 1002, "message": "卡片上下文缺少 task_id", "data": None}
            # 从 form_value 解析后置勾选（checker name=post_<id>，值 bool，勾选=要执行）
            post_ids = _extract_checked_ids(form_value, "post_")
            # 后置名称从 card_registry context 查
            post_map = {p["id"]: p["name"] for p in ctx.get("post_subtasks", [])}
            post_subtasks = [
                PostSubtaskInput(name=post_map[pid]) for pid in post_ids if pid in post_map
            ]
            # 事务内：INSERT subtasks（勾选的后置，可全取消）（<200ms）；立即返回
            data = TaskAppSvc(db).post_confirm(task_id, _DEFAULT_USER_ID, post_subtasks)
            # 事务后异步：opencode run 执行后置（3 秒超时内不阻塞）
            if data.async_triggered:
                background_tasks.add_task(TaskAppSvc.trigger_post_async, task_id)
            # 同步返回终态卡片（方案 B）：绿色确认后中间态（doc/09 §S4B 状态2）
            card = TaskAppSvc.build_post_confirm_done_card_from_db(
                db, task_id, data.post_subtask_count > 0
            )
            return {
                "toast": {"type": "success", "content": "已确认后置"},
                "card": {"type": "raw", "data": card},
            }

        # S5 确认日终总结（doc/09 §S5 状态1->2）
        if card_type == "daily_summary":
            daily_id = ctx.get("daily_id", "")
            if not daily_id:
                return {"code": 1002, "message": "卡片上下文缺少 daily_id", "data": None}
            # 从 form_value 解析 checker 任务状态（name=task_<id>，值 bool=已完成）
            # 对比初始 checked 状态反转变化的任务（doc/09 §S5 实现注意）：
            # builder 渲染初始 checked（已完成=checked），webhook 拿 form_value 后对比反转。
            # 初始状态 = DB 当前 task.status（card 从 DB 构建）。
            for k, v in form_value.items():
                if not k.startswith("task_") or k.endswith("_reassign"):
                    continue
                task_id = k[len("task_") :]
                target_completed = bool(v)
                # 查当前 DB 状态
                task = TaskAppSvc(db).task_repo.get(task_id)
                if task is None:
                    continue
                if target_completed and task.status != "已完成":
                    # 反转：未完成 -> 已完成（forward）
                    TaskAppSvc(db).patch_status(task_id, "已完成", triggered_by="user")
                elif not target_completed and task.status == "已完成":
                    # 反转：已完成 -> 未完成（revert，系统自动填 reason D18）
                    TaskAppSvc(db).patch_status(task_id, "待执行", triggered_by="user")
            # 事务内：UPDATE is_confirmed + COMMIT（<200ms）；立即返回
            data = DailyAppSvc(db).confirm_summary(daily_id)
            # 事务后异步：写 daily.md 快照（3 秒超时内不阻塞）
            background_tasks.add_task(DailyAppSvc.write_daily_md_async, daily_id)
            # 同步返回终态卡片（方案 B）：绿色已确认态（doc/09 §S5 状态2）
            card = DailyAppSvc.build_summary_done_card_from_db(db, daily_id)
            if card is None:
                return {"code": 1002, "message": "daily 记录不存在", "data": None}
            return {
                "toast": {"type": "success", "content": "日终总结已确认"},
                "card": {"type": "raw", "data": card},
            }

        # S4A 场景4 确认完成（doc/09 §S4A 场景4）
        if card_type == "task_complete":
            # 从 form_value 取 checker：task_<id>=true（确认完成）+
            # task_<id>_reassign=true（改交智能体重新执行）
            # 互斥判定（doc/09 §S4A 实现注意）：reassign=true 不走确认完成，
            # 而是改 executor=agent + 重新下发（铁律8 executor 可改，D26）
            reassigned: list[str] = []
            completed: list[str] = []
            for k, v in form_value.items():
                if not k.startswith("task_"):
                    continue
                if k.endswith("_reassign"):
                    if v:
                        reassigned.append(k[len("task_") : -len("_reassign")])
                elif v:
                    task_id = k[len("task_") :]
                    if task_id not in reassigned:
                        completed.append(task_id)
            # 确认完成：即时级联（事务内 <200ms）
            results = []
            for tid in completed:
                data = TaskAppSvc(db).confirm_complete(tid, _DEFAULT_USER_ID)
                results.append({"task_id": tid, "action": "completed"})
            # reassign：改 executor=agent（事务内），事务后异步下发（铁律 §3#3/#4）
            for tid in reassigned:
                data = TaskAppSvc(db).reassign_to_agent(tid, _DEFAULT_USER_ID)
                results.append({"task_id": tid, "action": "reassigned"})
                # 事务后异步：start_agent_serve（IO，BackgroundTasks）
                background_tasks.add_task(TaskAppSvc.reassign_to_agent_async, tid)
            # 同步返回终态卡片（方案 B）：绿色确认完成已提交态（doc/09 §S4A 场景4 点确认完成后）
            workspace_id = ctx.get("workspace_id", "")
            card = TaskAppSvc.build_task_complete_done_card_from_db(db, workspace_id, results)
            return {
                "toast": {"type": "success", "content": "确认完成已提交"},
                "card": {"type": "raw", "data": card},
            }

        # 未知 card_type
        logger.warning("confirm_btn: 未知卡片类型 %s, message_id=%s", card_type, message_id)
        return {"code": 1002, "message": f"未知卡片类型: {card_type}", "data": None}

    # 未知 btn_name -> noop
    return {"code": 0, "message": "noop", "data": None}
