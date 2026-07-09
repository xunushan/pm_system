"""子任务模板接口。详见《服务API文档 v2.0》3.10。

子任务模板 CRUD（scope_type=theme/phase，阶段级优先于专题级，同名去重）。
走 H5 页面，不建 Skill（doc/03 8.13）。

GET    /subtask-templates           查询模板列表（含合并查询，支持 task_id 参数）
POST   /subtask-templates            创建模板（3001 冲突）
PUT    /subtask-templates/{id}        更新模板（3001 冲突）
DELETE /subtask-templates/{id}        删除模板（标记 inactive，非物理删除）
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.common import ApiResponse
from app.schemas.subtask_template import (
    SubtaskTemplateCreateRequest,
    SubtaskTemplateData,
    SubtaskTemplateDeleteData,
    SubtaskTemplateListData,
    SubtaskTemplateUpdateRequest,
)
from app.services.config_app_svc import ConfigAppSvc

router = APIRouter()

DBSession = Annotated[Session, Depends(get_db)]


@router.get("", response_model=ApiResponse[SubtaskTemplateListData])
def list_templates(
    db: DBSession,
    scope_type: str | None = None,
    scope_id: str | None = None,
    type: str | None = None,
    status: str | None = None,
    task_id: str | None = None,
) -> ApiResponse[SubtaskTemplateListData]:
    """查询模板列表。

    - 无 task_id：按 scope_type/scope_id/type/status 过滤（H5 页面用）。
    - 有 task_id：合并查询（task -> phase_id -> theme_id，阶段优先专题，同名去重）。
      可配合 type 参数过滤前置/后置。
    """
    svc = ConfigAppSvc(db)
    if task_id is not None:
        # task_id 分支：合并查询（type 校验在 service 层 list_merged_by_task 内）
        data = svc.list_merged_by_task(task_id, type=type)
    else:
        # 普通过滤查询（type/scope_type/status 校验在 service 层 list_templates 内）
        data = svc.list_templates(
            scope_type=scope_type, scope_id=scope_id, type=type, status=status
        )
    return ApiResponse(data=data)


@router.post("", response_model=ApiResponse[SubtaskTemplateData])
def create_template(
    payload: SubtaskTemplateCreateRequest, db: DBSession
) -> ApiResponse[SubtaskTemplateData]:
    """创建模板。UNIQUE(scope_id,type,name) 冲突 -> 3001。"""
    data = ConfigAppSvc(db).create_template(payload)
    return ApiResponse(data=data)


@router.put("/{template_id}", response_model=ApiResponse[SubtaskTemplateData])
def update_template(
    template_id: str, payload: SubtaskTemplateUpdateRequest, db: DBSession
) -> ApiResponse[SubtaskTemplateData]:
    """更新模板。name 变更触发 UNIQUE 检查 -> 3001。"""
    data = ConfigAppSvc(db).update_template(template_id, payload)
    return ApiResponse(data=data)


@router.delete("/{template_id}", response_model=ApiResponse[SubtaskTemplateDeleteData])
def delete_template(template_id: str, db: DBSession) -> ApiResponse[SubtaskTemplateDeleteData]:
    """删除模板：标记 inactive（非物理删除，可恢复，幂等）。"""
    data = ConfigAppSvc(db).delete_template(template_id)
    return ApiResponse(data=data)
