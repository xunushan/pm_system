"""通用响应封装与错误。详见《服务API文档 v2.0》2.2/2.3。

统一响应：{ "code": 0, "message": "success", "data": { ... } }
统一错误：{ "code": 1001, "message": "...", "data": null }
"""

from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """统一响应封装。"""

    code: int = 0
    message: str = "success"
    data: T | None = None


# 错误码常量（doc/04 2.3）
CODE_SUCCESS = 0
CODE_NOT_FOUND = 1001
CODE_BAD_PARAM = 1002
CODE_CONFLICT = 1003
CODE_DRAFT_EXPIRED = 1007
CODE_INTERNAL = 5000
