"""Test data builders that go through the real service layer."""

import uuid
from dataclasses import dataclass

from httpx import AsyncClient

from glasshaus.core.context import Actor
from glasshaus.core.rbac import OrgRole, Scope
from glasshaus.db import apply_tenant, system_session, unit_of_work
from glasshaus.identity import security
from glasshaus.identity import service as identity
from glasshaus.identity.models import User
from glasshaus.identity.schemas import ApiTokenCreate, WorkspaceCreate
from glasshaus.models import Tenant
from glasshaus.projects import service as projects
from glasshaus.projects.schemas import ProjectCreate, ProjectDetail

PASSWORD = "correct horse battery staple"


def actor_for(user: User) -> Actor:
    return Actor(tenant_id=user.tenant_id, user_id=user.id, org_role=user.org_role, method="session")


async def make_tenant() -> Tenant:
    async with system_session() as session:
        tenant = Tenant(slug=f"t-{uuid.uuid4().hex[:10]}", name="Test org")
        session.add(tenant)
        await session.flush()
        return tenant


async def make_user(tenant: Tenant, role: OrgRole = OrgRole.MEMBER, *, email: str | None = None) -> User:
    async with system_session() as session:
        await apply_tenant(session, tenant.id)
        user = User(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            email=email or f"{uuid.uuid4().hex[:8]}@example.com",
            name="Test User",
            org_role=role,
            password_hash=security.hash_password(PASSWORD),
        )
        session.add(user)
        await session.flush()
        return user


async def token_for(user: User, scopes: tuple[Scope, ...] | None = None) -> str:
    if scopes is None:
        scopes = (
            (Scope.ADMIN,)
            if user.org_role in (OrgRole.OWNER, OrgRole.ADMIN)
            else (Scope.READ, Scope.TASKS_WRITE, Scope.PROJECTS_WRITE)
        )
    async with unit_of_work(actor_for(user)) as ctx:
        created = await identity.create_api_token(ctx, ApiTokenCreate(name="test", scopes=list(scopes)))
    return created.token


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@dataclass
class World:
    tenant: Tenant
    owner: User
    owner_token: str
    workspace_id: uuid.UUID
    project: ProjectDetail

    @property
    def headers(self) -> dict[str, str]:
        return auth(self.owner_token)


async def make_world(key: str | None = None) -> World:
    tenant = await make_tenant()
    owner = await make_user(tenant, OrgRole.OWNER)
    async with unit_of_work(actor_for(owner)) as ctx:
        ws = await identity.create_workspace(ctx, WorkspaceCreate(name="Main", slug="main"))
        project = await projects.create_project(
            ctx,
            ProjectCreate(workspace_id=ws.id, key=key or "P" + uuid.uuid4().hex[:5].upper(), name="Project"),
        )
    return World(tenant, owner, await token_for(owner), ws.id, project)


async def create_task(client: AsyncClient, world: World, **fields: object) -> dict:  # type: ignore[type-arg]
    body = {"project_id": str(world.project.id), "title": "A task", **fields}
    r = await client.post("/api/v1/tasks", json=body, headers=world.headers)
    assert r.status_code == 201, r.text
    data: dict = r.json()  # type: ignore[type-arg]
    return data


async def add_member(client: AsyncClient, world: World, user: User, role: str) -> None:
    r = await client.put(
        f"/api/v1/projects/{world.project.id}/members",
        json={"user_id": str(user.id), "role": role},
        headers=world.headers,
    )
    assert r.status_code == 200, r.text


async def events_for(aggregate_id: str, type_: str) -> list[dict]:  # type: ignore[type-arg]
    """Domain-event envelopes as consumers receive them."""
    from sqlalchemy import select

    from glasshaus.core.events import envelope
    from glasshaus.core.models import DomainEventRecord

    async with system_session() as session:
        rows = await session.scalars(
            select(DomainEventRecord)
            .where(DomainEventRecord.aggregate_id == uuid.UUID(aggregate_id), DomainEventRecord.type == type_)
            .order_by(DomainEventRecord.occurred_at)
        )
        return [envelope(r) for r in rows.all()]
