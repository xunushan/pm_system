"""drafts 请求/响应模型。详见《服务API文档 v2.0》3.1。

content 为任意 JSON 对象（plan 态含 goal+themes+phases+tasks，可达几十 KB）。
DB 中以 TEXT(JSON 字符串) 存储，API 层按 dict 透传。
"""

from datetime import datetime

from pydantic import BaseModel, Field


class DraftCreateRequest(BaseModel):
    user_id: str = Field(..., description="用户 ID")
    story_type: str = Field(..., description="plan/schedule/daily/weekly/edit/config")
    content: dict = Field(..., description="规划 JSON（goal+themes+phases+tasks 等）")
    expires_at: datetime | None = Field(None, description="过期时间（24h）")


class DraftCreateData(BaseModel):
    draft_id: str
    status: str
    created_at: datetime
    expires_at: datetime | None


class DraftGetData(BaseModel):
    draft_id: str
    user_id: str
    story_type: str
    entity_id: str | None
    content: dict
    status: str
    version: int
    created_at: datetime
    expires_at: datetime | None


class DraftUpdateRequest(BaseModel):
    content: dict
    version: int = Field(..., description="乐观锁：当前 version")


class DraftUpdateData(BaseModel):
    draft_id: str
    version: int
