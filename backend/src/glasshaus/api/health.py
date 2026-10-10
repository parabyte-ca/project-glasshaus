"""Liveness, readiness and version endpoints."""

import asyncio
from functools import lru_cache
from importlib import metadata
from typing import Literal

from fastapi import APIRouter, Response, status
from pydantic import BaseModel

from glasshaus.config import get_settings
from glasshaus.db import ping_database
from glasshaus.redis_client import ping_redis
from glasshaus.version import BUILD_SHA, __version__

router = APIRouter(tags=["system"])


class VersionInfo(BaseModel):
    name: str = "Project Glasshaus"
    version: str
    build: str
    license: str = "AGPL-3.0-only"
    source: str = ""  # the source code of this server (AGPL-3.0 section 13)


class Package(BaseModel):
    name: str
    version: str
    license: str


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
    return VersionInfo(version=__version__, build=BUILD_SHA, source=get_settings().source_url)


def _license(meta: metadata.PackageMetadata) -> str:
    if expr := meta.get("License-Expression"):
        return str(expr)
    classifiers = [
        c.rsplit(" :: ", 1)[-1] for c in meta.get_all("Classifier") or [] if c.startswith("License ::")
    ]
    text = (meta.get("License") or "").strip()
    return ", ".join(classifiers) or (text.splitlines()[0][:80] if text else "see package")


@lru_cache
def _packages() -> list[Package]:
    seen: dict[str, Package] = {}
    for dist in metadata.distributions():
        name = dist.metadata.get("Name") or ""
        if name and name.lower() != "glasshaus":
            seen[name.lower()] = Package(name=name, version=dist.version, license=_license(dist.metadata))
    return sorted(seen.values(), key=lambda p: p.name.lower())


@router.get(
    "/api/v1/licenses",
    summary="Third-party software in this server and its licences",
    response_model=list[Package],
)
async def licenses() -> list[Package]:
    return _packages()
