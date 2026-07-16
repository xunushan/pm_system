"""H5 看板编辑接口（Story9，入口 C）。详见《服务API文档 v2.0》§3.12 + 《系统架构文档》四。

H5 页面调本组接口：字段编辑 / 增删任务（物理删除）/ 阶段排序 / 状态变更
（暂停填 reason / 恢复 / 回退填 reason）。DB 为唯一真相源，无反向同步。

PUT  /board/{entity}/{id}        字段编辑
POST /board/{entity}/{id}/status 状态变更（暂停/恢复/回退，含 reason + 即时级联）
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.board import (
    BoardStatusData,
    BoardStatusRequest,
    BoardUpdateData,
    BoardUpdateRequest,
)
from app.schemas.common import ApiResponse
from app.services.board_app_svc import BoardAppSvc

router = APIRouter()

DBSession = Annotated[Session, Depends(get_db)]


@router.put("/{entity}/{entity_id}", response_model=ApiResponse[BoardUpdateData])
def update_fields(
    entity: str, entity_id: str, payload: BoardUpdateRequest, db: DBSession
) -> ApiResponse[BoardUpdateData]:
    """H5 字段编辑（名称/描述/deadline/executor）+ 增删任务 + 阶段排序。

    managed/path 不可改（激活后不能改，doc/01 S2 AC：激活后不能修改项目空间模式）。
    任务排序不支持（交给 pm-daily，doc/01 S3 AC：用户只能勾选/取消候选任务，不能新增）。
    """
    data = BoardAppSvc(db).update_fields(entity, entity_id, payload.fields)
    return ApiResponse(data=data)


@router.post("/{entity}/{entity_id}/status", response_model=ApiResponse[BoardStatusData])
def change_status(
    entity: str,
    entity_id: str,
    payload: BoardStatusRequest,
    db: DBSession,
) -> ApiResponse[BoardStatusData]:
    """H5 状态变更（暂停填 reason / 恢复 / 回退填 reason + 即时级联）。

    board 不提供 forward 激活（走 /schedules/activate，带工作空间初始化）。
    """
    data = BoardAppSvc(db).change_status(
        entity=entity,
        entity_id=entity_id,
        to_status=payload.to_status,
        reason=payload.reason,
        triggered_by=payload.triggered_by,
    )
    return ApiResponse(data=data)
