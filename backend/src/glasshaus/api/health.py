"""Liveness, readiness and version endpoints."""

import asyncio
from typing import Literal

from fastapi import APIRouter, Response, status
from pydantic import BaseModel

from glasshaus.db import ping_database
from glasshaus.redis_client import ping_redis
from glasshaus.version import BUILD_SHA, __version__

router = APIRouter(tags=["system"])


class VersionInfo(BaseModel):
    name: str = "Project Glasshaus"
    version: str
    build: str


class Readiness(BaseModel):
    status: Literal["ok", "degraded"]
    checks: dict[str, str]


@router.get("/healthz", summary="Liveness probe")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz", summary="Readiness probe (database and Redis)", response_model=Readiness)
async def readyz(response: Response) -> Readiness:
    checks: dict[str, str] = {}
    for name, probe in (("database", ping_database), ("redis", ping_redis)):
        try:
            await asyncio.wait_for(probe(), timeout=2)
            checks[name] = "ok"
        except Exception as exc:  # noqa: BLE001 - report any failure as not-ready
            checks[name] = f"error: {type(exc).__name__}"
    ok = all(v == "ok" for v in checks.values())
    if not ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return Readiness(status="ok" if ok else "degraded", checks=checks)


@router.get("/api/v1/version", summary="Running version", response_model=VersionInfo)
async def get_version() -> VersionInfo:
    return VersionInfo(version=__version__, build=BUILD_SHA)
