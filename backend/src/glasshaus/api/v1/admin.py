"""Organization administration: governance settings, data export, account recovery, SCIM tokens."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Response, status

from glasshaus import backups
from glasshaus.api.deps import Ctx
from glasshaus.governance import service as governance
from glasshaus.governance.service import OrgSettingsRead, OrgSettingsUpdate, PasswordReset
from glasshaus.people import privacy
from glasshaus.people.privacy import EraseRequest, EraseResult
from glasshaus.scim import service as scim
from glasshaus.scim.service import ScimTokenCreate, ScimTokenCreated, ScimTokenRead

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/settings", response_model=OrgSettingsRead, summary="Organization governance settings")
async def get_settings(ctx: Ctx) -> OrgSettingsRead:
    return await governance.get_settings(ctx)


@router.patch("/settings", response_model=OrgSettingsRead, summary="Change retention settings")
async def update_settings(ctx: Ctx, data: OrgSettingsUpdate) -> OrgSettingsRead:
    return await governance.update_settings(ctx, data)


@router.get(
    "/backups",
    response_model=backups.BackupStatus,
    summary="Backups and the last restore drill (single-organization servers)",
)
async def backup_status(ctx: Ctx) -> backups.BackupStatus:
    return await backups.get_status(ctx)


@router.get(
    "/export",
    summary="Download all of this organization's data (zip of JSON Lines; secrets excluded)",
    response_class=Response,
    responses={200: {"content": {"application/zip": {}}, "description": "Zip archive"}},
)
async def export(ctx: Ctx) -> Response:
    return _zip(await governance.export_organization(ctx), "glasshaus-export")


@router.post(
    "/users/{user_id}/password",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Set a new password for a user (ends their sessions)",
)
async def reset_password(ctx: Ctx, user_id: uuid.UUID, data: PasswordReset) -> Response:
    await governance.reset_password(ctx, user_id, data)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/users/{user_id}/sessions/revoke",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Sign a user out everywhere (sessions, API tokens and connected apps)",
)
async def revoke_sessions(ctx: Ctx, user_id: uuid.UUID) -> Response:
    await governance.sign_out_everywhere(ctx, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/users/{user_id}/export",
    response_class=Response,
    summary="Download everything held about one person (a zip of JSON Lines files; audited)",
)
async def export_person(ctx: Ctx, user_id: uuid.UUID) -> Response:
    return _zip(await privacy.export_person(ctx, user_id), f"glasshaus-person-{user_id.hex[:8]}")


@router.post(
    "/users/{user_id}/erase",
    response_model=EraseResult,
    summary="Erase a person: keep their work, remove their name, email, sign-ins and comment text",
)
async def erase_person(ctx: Ctx, user_id: uuid.UUID, data: EraseRequest) -> EraseResult:
    return await privacy.erase_person(ctx, user_id, data)


@router.get("/scim-tokens", response_model=list[ScimTokenRead], summary="SCIM provisioning tokens")
async def list_scim_tokens(ctx: Ctx) -> list[ScimTokenRead]:
    return await scim.list_tokens(ctx)


@router.post(
    "/scim-tokens",
    response_model=ScimTokenCreated,
    status_code=status.HTTP_201_CREATED,
    summary="Create a SCIM token (the secret is returned once)",
)
async def create_scim_token(ctx: Ctx, data: ScimTokenCreate) -> ScimTokenCreated:
    return await scim.create_token(ctx, data)


@router.delete(
    "/scim-tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Revoke a SCIM token"
)
async def revoke_scim_token(ctx: Ctx, token_id: uuid.UUID) -> Response:
    await scim.revoke_token(ctx, token_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _zip(data: bytes, stem: str) -> Response:
    name = f"{stem}-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.zip"
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"},
    )
