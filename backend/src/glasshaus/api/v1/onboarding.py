"""First-run guidance for the signed-in person (tour, checklist, feature tips)."""

from fastapi import APIRouter

from glasshaus.api.deps import Ctx
from glasshaus.onboarding import service as onboarding
from glasshaus.onboarding.schemas import OnboardingRead, OnboardingUpdate

router = APIRouter(tags=["users"])


@router.get(
    "/users/me/onboarding", response_model=OnboardingRead, summary="Your product tour and checklist progress"
)
async def get_onboarding(ctx: Ctx) -> OnboardingRead:
    return await onboarding.get_onboarding(ctx)


@router.patch(
    "/users/me/onboarding",
    response_model=OnboardingRead,
    summary="Record the tour as finished or skipped, hide the checklist, dismiss a tip, or start over",
)
async def update_onboarding(body: OnboardingUpdate, ctx: Ctx) -> OnboardingRead:
    return await onboarding.update_onboarding(ctx, body)
