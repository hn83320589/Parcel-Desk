"""領域例外：service 層只丟這些例外，由 main.py 統一轉成 HTTP 回應。"""

from fastapi import Request
from fastapi.responses import JSONResponse


class DomainError(Exception):
    status_code = 400
    code = "DOMAIN_ERROR"

    def __init__(self, message: str, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code:
            self.code = code


class NotFound(DomainError):
    status_code = 404
    code = "NOT_FOUND"


class Conflict(DomainError):
    status_code = 409
    code = "CONFLICT"


class Forbidden(DomainError):
    status_code = 403
    code = "FORBIDDEN"


class InvalidField(DomainError):
    """格式正確但內容無效的欄位（例如戶別不存在），回 422 並指出欄位位置。"""

    status_code = 422
    code = "INVALID_FIELD"

    def __init__(self, field: str, message: str, location: str = "body") -> None:
        super().__init__(message)
        self.field = field
        self.location = location


async def domain_error_handler(_request: Request, exc: DomainError) -> JSONResponse:
    if isinstance(exc, InvalidField):
        # 與 FastAPI 預設的 422 格式一致，前端可用同一套方式解析
        detail = [{"loc": [exc.location, exc.field], "msg": exc.message, "type": "value_error"}]
        return JSONResponse(status_code=exc.status_code, content={"detail": detail})
    return JSONResponse(
        status_code=exc.status_code, content={"detail": exc.message, "code": exc.code}
    )
