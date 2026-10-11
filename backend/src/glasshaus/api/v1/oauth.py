import uuid
from datetime import datetime

from fastapi import APIRouter, Response, status

from glasshaus.api.deps import Ctx
from glasshaus.audit import service as audit
from glasshaus.audit.service import AuditRead, ChainCheck
from glasshaus.oauth import service as oauth
from glasshaus.oauth.service import ConnectedApp, ConsentDecision, ConsentRequest, ConsentResult

router = APIRouter()


@router.get(
    "/oauth/requests/{request_id}",
    response_model=ConsentRequest,
    tags=["oauth"],
    summary="A pending MCP client authorization request (web app consent screen)",
)
async def get_consent(ctx: Ctx, request_id: str) -> ConsentRequest:
    return await oauth.get_consent(ctx, request_id)


@router.post(
    "/oauth/requests/{request_id}",
    response_model=ConsentResult,
    tags=["oauth"],
    summary="Approve or deny an authorization request; returns the client redirect",
)
async def decide_consent(ctx: Ctx, request_id: str, data: ConsentDecision) -> ConsentResult:
    return await oauth.decide(ctx, request_id, data)


@router.get(
    "/oauth/apps",
    response_model=list[ConnectedApp],
    tags=["oauth"],
    summary="Apps you have connected with OAuth",
)
async def list_apps(ctx: Ctx) -> list[ConnectedApp]:
    return await oauth.list_connected_apps(ctx)


@router.delete(
    "/oauth/apps/{app_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["oauth"],
    summary="Disconnect an app (revokes its tokens)",
)
async def revoke_app(ctx: Ctx, app_id: uuid.UUID) -> Response:
    await oauth.revoke_app(ctx, app_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/audit-log",
    response_model=list[AuditRead],
    tags=["audit"],
    summary="Audit log of MCP tool calls and other audited actions (organization admins)",
)
async def audit_log(
    ctx: Ctx,
    action: str | None = None,
    actor_id: uuid.UUID | None = None,
    outcome: str | None = None,
    before: datetime | None = None,
    limit: int = 100,
) -> list[AuditRead]:
    return await audit.list_entries(
        ctx, action=action, actor_id=actor_id, outcome=outcome, before=before, limit=limit
    )


@router.post(
    "/audit-log/verify",
    response_model=ChainCheck,
    tags=["audit"],
    summary="Check the audit log's hash chain: reports any entry changed, removed or inserted",
)
async def verify_audit_log(ctx: Ctx) -> ChainCheck:
    return await audit.verify(ctx)
