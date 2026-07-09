"""规划接口（Story1）。详见《服务API文档 v2.0》3.2。

POST /plans/confirm   确认方案：用 draft_id 读 drafts -> 写正式表 -> 删 drafts -> 给 H5 链接
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.common import ApiResponse
from app.schemas.plan import PlanConfirmData, PlanConfirmRequest
from app.services.plan_app_svc import PlanAppSvc

router = APIRouter()

DBSession = Annotated[Session, Depends(get_db)]


@router.post("/confirm", response_model=ApiResponse[PlanConfirmData])
def confirm_plan(payload: PlanConfirmRequest, db: DBSession) -> ApiResponse[PlanConfirmData]:
    data = PlanAppSvc(db).confirm(payload.draft_id)
    return ApiResponse(data=data)
