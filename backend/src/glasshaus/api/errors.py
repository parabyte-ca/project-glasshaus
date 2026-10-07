"""RFC 9457 problem details for every error the API returns."""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from glasshaus.core.errors import ServiceError

PROBLEM_BASE = "https://glasshaus.dev/problems/"
MEDIA_TYPE = "application/problem+json"


class Problem(BaseModel):
    type: str
    title: str
    status: int
    detail: str
    code: str
    errors: list[dict[str, Any]] | None = None


def problem(status: int, code: str, detail: str, **extra: Any) -> JSONResponse:
    body = {
        "type": PROBLEM_BASE + code,
        "title": code.replace("_", " ").capitalize(),
        "status": status,
        "detail": detail,
        "code": code,
        **extra,
    }
    headers = {"WWW-Authenticate": "Bearer"} if status == 401 else None
    return JSONResponse(body, status_code=status, media_type=MEDIA_TYPE, headers=headers)


PROBLEM_RESPONSES: dict[int | str, dict[str, Any]] = {
    status: {"model": Problem, "content": {MEDIA_TYPE: {}}, "description": desc}
    for status, desc in (
        (401, "Not authenticated"),
        (403, "Permission denied"),
        (404, "Not found"),
        (422, "Invalid input"),
    )
}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ServiceError)
    async def _service(_: Request, exc: ServiceError) -> JSONResponse:
        return problem(exc.status, exc.code, exc.detail, **exc.extra)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
        return problem(422, "invalid_input", "request validation failed", errors=errors)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "not_found", 405: "method_not_allowed", 401: "unauthenticated"}.get(
            exc.status_code, "http_error"
        )
        return problem(exc.status_code, code, str(exc.detail))
