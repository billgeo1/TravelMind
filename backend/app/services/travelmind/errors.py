"""TravelMind 统一错误处理。

所有新接口返回统一错误结构::

    {"error": {"code": "...", "message": "...", "retryable": false}}

这样前端可以用同一套逻辑处理 400/409/413/415/422/429/503。
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class ErrorCode:
    """规范第 8 节定义的错误码。"""

    INVALID_INPUT = "INVALID_INPUT"
    IMAGE_TOO_LARGE = "IMAGE_TOO_LARGE"
    UNSUPPORTED_IMAGE = "UNSUPPORTED_IMAGE"
    VISION_NOT_CONFIGURED = "VISION_NOT_CONFIGURED"
    EXTERNAL_PROVIDER_UNAVAILABLE = "EXTERNAL_PROVIDER_UNAVAILABLE"
    NO_FEASIBLE_PLAN = "NO_FEASIBLE_PLAN"
    STALE_PLAN_REVISION = "STALE_PLAN_REVISION"
    RATE_LIMITED = "RATE_LIMITED"


# 错误码 -> (HTTP 状态码, 是否可重试)
_DEFAULTS: dict[str, tuple[int, bool]] = {
    ErrorCode.INVALID_INPUT: (422, False),
    ErrorCode.IMAGE_TOO_LARGE: (413, False),
    ErrorCode.UNSUPPORTED_IMAGE: (415, False),
    ErrorCode.VISION_NOT_CONFIGURED: (503, False),
    ErrorCode.EXTERNAL_PROVIDER_UNAVAILABLE: (503, True),
    ErrorCode.NO_FEASIBLE_PLAN: (422, False),
    ErrorCode.STALE_PLAN_REVISION: (409, True),
    ErrorCode.RATE_LIMITED: (429, True),
}


class TravelMindError(Exception):
    """业务异常,携带统一错误码。"""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int | None = None,
        retryable: bool | None = None,
    ) -> None:
        default_status, default_retryable = _DEFAULTS.get(code, (400, False))
        self.code = code
        self.message = message
        self.status_code = status_code if status_code is not None else default_status
        self.retryable = default_retryable if retryable is None else retryable
        super().__init__(message)

    def to_body(self) -> dict:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "retryable": self.retryable,
            }
        }


def register_exception_handlers(app: FastAPI) -> None:
    """为 FastAPI 应用注册 TravelMind 统一异常处理。"""

    @app.exception_handler(TravelMindError)
    async def _handle_travelmind_error(_: Request, exc: TravelMindError):
        return JSONResponse(status_code=exc.status_code, content=exc.to_body())

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(_: Request, exc: RequestValidationError):
        first = exc.errors()[0] if exc.errors() else {}
        location = ".".join(str(part) for part in first.get("loc", ()))
        detail = first.get("msg", "请求参数不合法")
        message = f"请求参数不合法: {location} {detail}".strip()
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": ErrorCode.INVALID_INPUT,
                    "message": message,
                    "retryable": False,
                },
                # 兼容旧前端:保留 FastAPI 默认错误字段,避免破坏原有请求的错误提示
                "detail": message,
            },
        )
