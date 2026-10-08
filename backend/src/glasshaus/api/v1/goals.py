import uuid

from fastapi import APIRouter, status

from glasshaus.api.deps import Ctx
from glasshaus.goals import service as goals
from glasshaus.goals.schemas import (
    CheckInCreate,
    CheckInRead,
    KeyResultCreate,
    KeyResultRead,
    KeyResultUpdate,
    ObjectiveCreate,
    ObjectiveRead,
    ObjectiveUpdate,
    PortfolioCreate,
    PortfolioDetail,
    PortfolioRead,
    PortfolioUpdate,
)

router = APIRouter()


@router.get("/portfolios", response_model=list[PortfolioRead], tags=["portfolios"], summary="List portfolios")
async def list_portfolios(ctx: Ctx) -> list[PortfolioRead]:
    return await goals.list_portfolios(ctx)


@router.post(
    "/portfolios",
    response_model=PortfolioDetail,
    status_code=status.HTTP_201_CREATED,
    tags=["portfolios"],
    summary="Create a portfolio",
)
async def create_portfolio(body: PortfolioCreate, ctx: Ctx) -> PortfolioDetail:
    return await goals.create_portfolio(ctx, body)


@router.get(
    "/portfolios/{portfolio_id}",
    response_model=PortfolioDetail,
    tags=["portfolios"],
    summary="A portfolio with each project's health",
)
async def get_portfolio(portfolio_id: uuid.UUID, ctx: Ctx) -> PortfolioDetail:
    return await goals.get_portfolio(ctx, portfolio_id)


@router.patch(
    "/portfolios/{portfolio_id}",
    response_model=PortfolioDetail,
    tags=["portfolios"],
    summary="Change a portfolio",
)
async def update_portfolio(portfolio_id: uuid.UUID, body: PortfolioUpdate, ctx: Ctx) -> PortfolioDetail:
    return await goals.update_portfolio(ctx, portfolio_id, body)


@router.delete(
    "/portfolios/{portfolio_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["portfolios"],
    summary="Delete a portfolio",
)
async def delete_portfolio(portfolio_id: uuid.UUID, ctx: Ctx) -> None:
    await goals.delete_portfolio(ctx, portfolio_id)


@router.get("/objectives", response_model=list[ObjectiveRead], tags=["okrs"], summary="List objectives")
async def list_objectives(ctx: Ctx, period: str | None = None) -> list[ObjectiveRead]:
    return await goals.list_objectives(ctx, period=period)


@router.post(
    "/objectives",
    response_model=ObjectiveRead,
    status_code=status.HTTP_201_CREATED,
    tags=["okrs"],
    summary="Create an objective with key results",
)
async def create_objective(body: ObjectiveCreate, ctx: Ctx) -> ObjectiveRead:
    return await goals.create_objective(ctx, body)


@router.get(
    "/objectives/{objective_id}", response_model=ObjectiveRead, tags=["okrs"], summary="Get an objective"
)
async def get_objective(objective_id: uuid.UUID, ctx: Ctx) -> ObjectiveRead:
    return await goals.get_objective(ctx, objective_id)


@router.patch(
    "/objectives/{objective_id}", response_model=ObjectiveRead, tags=["okrs"], summary="Change an objective"
)
async def update_objective(objective_id: uuid.UUID, body: ObjectiveUpdate, ctx: Ctx) -> ObjectiveRead:
    return await goals.update_objective(ctx, objective_id, body)


@router.delete(
    "/objectives/{objective_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["okrs"],
    summary="Delete an objective",
)
async def delete_objective(objective_id: uuid.UUID, ctx: Ctx) -> None:
    await goals.delete_objective(ctx, objective_id)


@router.post(
    "/objectives/{objective_id}/key-results",
    response_model=KeyResultRead,
    status_code=status.HTTP_201_CREATED,
    tags=["okrs"],
    summary="Add a key result",
)
async def add_key_result(objective_id: uuid.UUID, body: KeyResultCreate, ctx: Ctx) -> KeyResultRead:
    return await goals.add_key_result(ctx, objective_id, body)


@router.patch(
    "/key-results/{kr_id}", response_model=KeyResultRead, tags=["okrs"], summary="Change a key result"
)
async def update_key_result(kr_id: uuid.UUID, body: KeyResultUpdate, ctx: Ctx) -> KeyResultRead:
    return await goals.update_key_result(ctx, kr_id, body)


@router.delete(
    "/key-results/{kr_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["okrs"],
    summary="Delete a key result",
)
async def delete_key_result(kr_id: uuid.UUID, ctx: Ctx) -> None:
    await goals.delete_key_result(ctx, kr_id)


@router.get(
    "/key-results/{kr_id}/check-ins",
    response_model=list[CheckInRead],
    tags=["okrs"],
    summary="Check-in history",
)
async def list_check_ins(kr_id: uuid.UUID, ctx: Ctx) -> list[CheckInRead]:
    return await goals.list_check_ins(ctx, kr_id)


@router.post(
    "/key-results/{kr_id}/check-ins",
    response_model=CheckInRead,
    status_code=status.HTTP_201_CREATED,
    tags=["okrs"],
    summary="Record progress and confidence",
)
async def check_in(kr_id: uuid.UUID, body: CheckInCreate, ctx: Ctx) -> CheckInRead:
    return await goals.check_in(ctx, kr_id, body)
