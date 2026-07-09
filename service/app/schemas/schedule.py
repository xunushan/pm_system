"""调度确认请求/响应模型。详见《服务API文档 v2.0》3.3。

patch 卡片形式：卡片 A 多选专题+设 managed/path；卡片 B 填各阶段 deadline。
confirm 收齐两者，事务内激活+级联+审计，事务后异步初始化工作空间。
"""

from datetime import date

from pydantic import BaseModel, Field


class ScheduleItem(BaseModel):
    """单个专题的调度项（卡片 A managed/path + 卡片 B deadline 汇聚于此）。"""

    theme_id: str
    managed: bool = True
    # managed=0 时必填（AppSvc 校验）；managed=1 时由系统生成、忽略传入
    path: str | None = None
    # 可选：客户端预锁定的阶段；不传则系统锁定，传了则校验一致
    phase_id: str | None = None
    # 必填（AppSvc 校验 None -> 400/1002，统一错误码而非 pydantic 422）
    deadline: date | None = None


class ScheduleConfirmRequest(BaseModel):
    user_id: str
    goal_id: str
    items: list[ScheduleItem] = Field(..., min_length=1)


class ActivatedPhase(BaseModel):
    phase_id: str
    name: str
    deadline: date
    workspace_id: str
    workspace_managed: bool
    # 真实 DB 状态：managed=1 -> '未初始化'（异步初始化中）；managed=0 -> '已就绪'
    workspace_status: str


class ScheduleConfirmData(BaseModel):
    activated_phases: list[ActivatedPhase]
    scheduled_start_date: date | None
    bitable_synced: bool = False
