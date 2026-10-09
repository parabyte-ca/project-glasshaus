"""Phone and desktop notifications (Web Push), turned on per device."""

from fastapi import APIRouter, Response, status
from pydantic import Field

from glasshaus import push
from glasshaus.api.deps import Ctx, CurrentActor
from glasshaus.core.schemas import Schema
from glasshaus.push import PushStatus, PushSubscriptionCreate

router = APIRouter(prefix="/push", tags=["notifications"])


class PushEndpoint(Schema):
    endpoint: str = Field(min_length=10, max_length=1000)


@router.get(
    "", response_model=PushStatus, summary="The server's push key and how many of your devices are on"
)
async def push_status(ctx: Ctx) -> PushStatus:
    return await push.status(ctx)


@router.post(
    "/subscriptions",
    response_model=PushStatus,
    status_code=status.HTTP_201_CREATED,
    summary="Turn on notifications for this device (the browser's push subscription)",
)
async def subscribe(ctx: Ctx, data: PushSubscriptionCreate) -> PushStatus:
    return await push.subscribe(ctx, data)


@router.post(
    "/subscriptions/remove",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Turn off notifications for this device",
)
async def unsubscribe(ctx: Ctx, data: PushEndpoint) -> Response:
    await push.unsubscribe(ctx, data.endpoint)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/test", response_model=dict[str, int], summary="Send a test notification to your devices")
async def test(actor: CurrentActor) -> dict[str, int]:
    return await push.send_test(actor)
