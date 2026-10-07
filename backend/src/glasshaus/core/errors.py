"""Service-layer errors. Adapters (REST, MCP) translate these; services never raise HTTP errors."""

from typing import Any


class ServiceError(Exception):
    code = "error"
    status = 400

    def __init__(self, detail: str, *, extra: dict[str, Any] | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        self.extra = extra or {}


class NotFound(ServiceError):
    code = "not_found"
    status = 404


class PermissionDenied(ServiceError):
    code = "permission_denied"
    status = 403


class Unauthenticated(ServiceError):
    code = "unauthenticated"
    status = 401


class Conflict(ServiceError):
    code = "conflict"
    status = 409


class PreconditionFailed(ServiceError):
    code = "precondition_failed"
    status = 412


class InvalidInput(ServiceError):
    code = "invalid_input"
    status = 422


class RateLimited(ServiceError):
    code = "rate_limited"
    status = 429
