"""飞书卡片回调入口（入口 B）。

飞书 3 秒超时：回调仅做 DB 写 + 即时级联（<200ms）后立即返回；
耗时操作（工作空间初始化、异步执行、推送）事务提交后异步。

详见《系统架构文档 v2.0》8.1 / 《服务API文档 v2.0》webhook 节。
"""

from fastapi import APIRouter, Request

router = APIRouter()


@router.post("/feishu/card")
async def feishu_card_callback(request: Request) -> dict:
    """飞书卡片按钮回调。

    TODO(各 Story): 解析 `action.value.action_id` -> 硬编码路由到对应 AppService。
    例如：
        action_id="plan.confirm"     -> PlanAppSvc.confirm(draft_id)
        action_id="schedule.confirm" -> ScheduleAppSvc.confirm(...)
        action_id="task.complete"    -> TaskAppSvc.complete(task_id)
    """
    payload = await request.json()
    action_value = (payload.get("action") or {}).get("value", {})
    return {
        "todo": "implement - 见 doc/03 8.1 / doc/04 webhook",
        "received": action_value,
    }
