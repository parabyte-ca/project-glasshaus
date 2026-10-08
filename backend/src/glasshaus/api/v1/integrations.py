"""Integrations: Slack, Microsoft Teams, signed webhooks, GitHub/GitLab, email-to-task, calendar feeds."""

import uuid

from fastapi import APIRouter, Request, Response, status

from glasshaus.api.deps import Ctx, Session
from glasshaus.integrations import service as integrations
from glasshaus.integrations.service import (
    EVENT_TYPES,
    CalendarFeedRead,
    DeliveryRead,
    IntegrationCreate,
    IntegrationCreated,
    IntegrationRead,
    IntegrationUpdate,
)

router = APIRouter(tags=["integrations"])
MAX_INBOUND_BYTES = 2 * 1024 * 1024


@router.get(
    "/integrations/event-types",
    response_model=list[str],
    summary="Event types outbound integrations can send",
)
async def event_types() -> list[str]:
    return EVENT_TYPES


@router.get(
    "/integrations",
    response_model=list[IntegrationRead],
    summary="List integrations (org admins, or a project's)",
)
async def list_integrations(ctx: Ctx, project_id: uuid.UUID | None = None) -> list[IntegrationRead]:
    return await integrations.list_integrations(ctx, project_id)


@router.post(
    "/integrations",
    response_model=IntegrationCreated,
    status_code=status.HTTP_201_CREATED,
    summary="Connect Slack, Teams, a webhook, GitHub/GitLab or a mailbox",
)
async def create_integration(ctx: Ctx, data: IntegrationCreate) -> IntegrationCreated:
    return await integrations.create_integration(ctx, data)


@router.get("/integrations/{integration_id}", response_model=IntegrationRead, summary="Get an integration")
async def get_integration(ctx: Ctx, integration_id: uuid.UUID) -> IntegrationRead:
    return await integrations.get_integration(ctx, integration_id)


@router.patch(
    "/integrations/{integration_id}", response_model=IntegrationRead, summary="Update an integration"
)
async def update_integration(ctx: Ctx, integration_id: uuid.UUID, data: IntegrationUpdate) -> IntegrationRead:
    return await integrations.update_integration(ctx, integration_id, data)


@router.delete(
    "/integrations/{integration_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remove an integration"
)
async def delete_integration(ctx: Ctx, integration_id: uuid.UUID) -> Response:
    await integrations.delete_integration(ctx, integration_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/integrations/{integration_id}/test", response_model=DeliveryRead, summary="Send a test message"
)
async def test_integration(ctx: Ctx, integration_id: uuid.UUID) -> DeliveryRead:
    return await integrations.test_integration(ctx, integration_id)


@router.get(
    "/integrations/{integration_id}/deliveries",
    response_model=list[DeliveryRead],
    summary="Recent deliveries",
)
async def list_deliveries(ctx: Ctx, integration_id: uuid.UUID, limit: int = 50) -> list[DeliveryRead]:
    return await integrations.list_deliveries(ctx, integration_id, limit)


@router.post(
    "/integrations/{integration_id}/inbound",
    summary="Payload URL for GitHub/GitLab webhooks (signature-verified)",
    responses={200: {"description": "Processed"}},
)
async def inbound(integration_id: uuid.UUID, request: Request, session: Session) -> dict[str, object]:
    from glasshaus.core.errors import InvalidInput

    body = await request.body()
    if len(body) > MAX_INBOUND_BYTES:
        raise InvalidInput("payload too large")
    headers = {k.lower(): v for k, v in request.headers.items()}
    result = await integrations.handle_inbound(session, integration_id, headers, body)
    result.pop("events", None)  # relayed by the worker's outbox sweep after this transaction commits
    return result


@router.get("/calendar-feed", response_model=CalendarFeedRead, summary="Your private calendar feed (status)")
async def get_feed(ctx: Ctx) -> CalendarFeedRead:
    return await integrations.get_calendar_feed(ctx)


@router.post(
    "/calendar-feed",
    response_model=CalendarFeedRead,
    summary="Create or replace your calendar feed URL (Google, Microsoft 365, Apple subscribe to it)",
)
async def reset_feed(ctx: Ctx) -> CalendarFeedRead:
    return await integrations.reset_calendar_feed(ctx)


@router.delete(
    "/calendar-feed", status_code=status.HTTP_204_NO_CONTENT, summary="Turn off your calendar feed"
)
async def delete_feed(ctx: Ctx) -> Response:
    await integrations.delete_calendar_feed(ctx)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/calendar/{token}",
    summary="iCalendar feed of your open, dated tasks (secret URL)",
    response_class=Response,
    responses={200: {"content": {"text/calendar": {}}}},
)
async def calendar(token: str, session: Session) -> Response:
    ics = await integrations.calendar_ics(session, token)
    return Response(
        ics, media_type="text/calendar; charset=utf-8", headers={"Cache-Control": "private, max-age=300"}
    )
