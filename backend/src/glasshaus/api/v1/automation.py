import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from glasshaus.api.deps import Ctx
from glasshaus.automation import service as automation
from glasshaus.automation import templates
from glasshaus.automation.schemas import (
    RecurringCreate,
    RecurringRead,
    RecurringUpdate,
    RuleCreate,
    RuleRead,
    RuleTestRequest,
    RuleTestResult,
    RuleUpdate,
    RunRead,
    RunStatus,
    TemplateCreate,
    TemplateInstantiate,
    TemplateRead,
)
from glasshaus.projects.schemas import ProjectDetail

router = APIRouter(tags=["automation"])


@router.get(
    "/projects/{project_id}/automation-rules", response_model=list[RuleRead], summary="List automation rules"
)
async def list_rules(project_id: uuid.UUID, ctx: Ctx) -> list[RuleRead]:
    return await automation.list_rules(ctx, project_id)


@router.post(
    "/projects/{project_id}/automation-rules",
    response_model=RuleRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a rule: trigger → conditions → actions (project admins)",
)
async def create_rule(project_id: uuid.UUID, body: RuleCreate, ctx: Ctx) -> RuleRead:
    return await automation.create_rule(ctx, project_id, body)


@router.post(
    "/projects/{project_id}/automation-rules/test",
    response_model=RuleTestResult,
    summary="Dry run a rule against a task (changes nothing)",
)
async def test_rule(project_id: uuid.UUID, body: RuleTestRequest, ctx: Ctx) -> RuleTestResult:
    return await automation.test_rule(ctx, project_id, body)


@router.get("/automation-rules/{rule_id}", response_model=RuleRead, summary="Get a rule")
async def get_rule(rule_id: uuid.UUID, ctx: Ctx) -> RuleRead:
    return await automation.get_rule(ctx, rule_id)


@router.patch(
    "/automation-rules/{rule_id}", response_model=RuleRead, summary="Update or enable/disable a rule"
)
async def update_rule(rule_id: uuid.UUID, body: RuleUpdate, ctx: Ctx) -> RuleRead:
    return await automation.update_rule(ctx, rule_id, body)


@router.post(
    "/automation-rules/{rule_id}/rotate-secret", response_model=RuleRead, summary="New webhook signing secret"
)
async def rotate_secret(rule_id: uuid.UUID, ctx: Ctx) -> RuleRead:
    return await automation.rotate_secret(ctx, rule_id)


@router.delete("/automation-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a rule")
async def delete_rule(rule_id: uuid.UUID, ctx: Ctx) -> None:
    await automation.delete_rule(ctx, rule_id)


@router.get(
    "/projects/{project_id}/automation-runs",
    response_model=list[RunRead],
    summary="Automation run log (newest first)",
)
async def list_runs(
    project_id: uuid.UUID,
    ctx: Ctx,
    rule_id: uuid.UUID | None = None,
    run_status: Annotated[RunStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[RunRead]:
    return await automation.list_runs(ctx, project_id, rule_id=rule_id, status=run_status, limit=limit)


@router.post(
    "/automation-runs/{run_id}/retry",
    response_model=RunRead,
    summary="Retry a failed run (only failed webhooks are resent if the actions succeeded)",
)
async def retry_run(run_id: uuid.UUID, ctx: Ctx) -> RunRead:
    return await automation.retry_run(ctx, run_id)


@router.get(
    "/projects/{project_id}/recurring-tasks",
    response_model=list[RecurringRead],
    summary="List recurring tasks",
)
async def list_recurring(project_id: uuid.UUID, ctx: Ctx) -> list[RecurringRead]:
    return await automation.list_recurring(ctx, project_id)


@router.post(
    "/projects/{project_id}/recurring-tasks",
    response_model=RecurringRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a task on a daily, weekly or monthly schedule",
)
async def create_recurring(project_id: uuid.UUID, body: RecurringCreate, ctx: Ctx) -> RecurringRead:
    return await automation.create_recurring(ctx, project_id, body)


@router.patch(
    "/recurring-tasks/{recurring_id}", response_model=RecurringRead, summary="Update a recurring task"
)
async def update_recurring(recurring_id: uuid.UUID, body: RecurringUpdate, ctx: Ctx) -> RecurringRead:
    return await automation.update_recurring(ctx, recurring_id, body)


@router.delete(
    "/recurring-tasks/{recurring_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a recurring task",
)
async def delete_recurring(recurring_id: uuid.UUID, ctx: Ctx) -> None:
    await automation.delete_recurring(ctx, recurring_id)


@router.get("/project-templates", response_model=list[TemplateRead], summary="List project templates")
async def list_templates(ctx: Ctx) -> list[TemplateRead]:
    return await templates.list_templates(ctx)


@router.post(
    "/project-templates",
    response_model=TemplateRead,
    status_code=status.HTTP_201_CREATED,
    summary="Save a project's structure as a template",
)
async def create_template(body: TemplateCreate, ctx: Ctx) -> TemplateRead:
    return await templates.create_template(ctx, body)


@router.get("/project-templates/{template_id}", response_model=TemplateRead, summary="Get a template")
async def get_template(template_id: uuid.UUID, ctx: Ctx) -> TemplateRead:
    return await templates.get_template(ctx, template_id)


@router.delete(
    "/project-templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a template"
)
async def delete_template(template_id: uuid.UUID, ctx: Ctx) -> None:
    await templates.delete_template(ctx, template_id)


@router.post(
    "/project-templates/{template_id}/instantiate",
    response_model=ProjectDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new project from a template",
)
async def instantiate_template(template_id: uuid.UUID, body: TemplateInstantiate, ctx: Ctx) -> ProjectDetail:
    return await templates.instantiate(ctx, template_id, body)
