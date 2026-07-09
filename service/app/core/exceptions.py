"""应用层业务异常。

AppSvc 抛出 AppError（含错误码 + HTTP 状态），由 FastAPI exception handler
统一转成 { "code": <code>, "message": <message>, "data": null } 响应。
错误码定义见《服务API文档 v2.0》2.3。
"""

from app.schemas.common import (
    CODE_BAD_PARAM,
    CODE_CONFLICT,
    CODE_DRAFT_EXPIRED,
    CODE_INTERNAL,
    CODE_NOT_FOUND,
    CODE_QUOTA_EXCEEDED,
    CODE_REASON_REQUIRED,
)


class AppError(Exception):
    """业务异常基类。code 对应 doc/04 2.3 错误码，http_status 为 HTTP 状态码。"""

    def __init__(self, code: int, message: str, http_status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


class NotFoundError(AppError):
    def __init__(self, message: str = "资源不存在") -> None:
        super().__init__(CODE_NOT_FOUND, message, http_status=404)


class ConflictError(AppError):
    def __init__(self, message: str = "状态冲突") -> None:
        super().__init__(CODE_CONFLICT, message, http_status=409)


class QuotaExceededError(AppError):
    """并发超限（doc/04 2.3: 1004，如全局进行中阶段>3）。"""

    def __init__(self, message: str = "并发超限") -> None:
        super().__init__(CODE_QUOTA_EXCEEDED, message, http_status=409)


class BadRequestError(AppError):
    def __init__(self, message: str = "参数错误") -> None:
        super().__init__(CODE_BAD_PARAM, message, http_status=400)


class DraftExpiredError(AppError):
    def __init__(self, message: str = "草稿已过期") -> None:
        super().__init__(CODE_DRAFT_EXPIRED, message, http_status=410)


class ReasonRequiredError(AppError):
    """回退/暂停需 reason（doc/04 2.3: 1005）。"""

    def __init__(self, message: str = "状态回退/暂停需 reason") -> None:
        super().__init__(CODE_REASON_REQUIRED, message, http_status=400)


class InternalError(AppError):
    def __init__(self, message: str = "内部错误") -> None:
        super().__init__(CODE_INTERNAL, message, http_status=500)
