"""Identity services: authentication, users, workspaces and API tokens."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from glasshaus.config import get_settings
from glasshaus.core import events
from glasshaus.core.authz import require_org, require_workspace
from glasshaus.core.context import Actor, ServiceContext
from glasshaus.core.errors import (
    Conflict,
    InvalidInput,
    NotFound,
    PermissionDenied,
    RateLimited,
    Unauthenticated,
)
from glasshaus.core.rbac import OrgRole, Permission, Scope, WorkspaceRole
from glasshaus.db import apply_tenant
from glasshaus.identity import security
from glasshaus.identity.models import (
    ASSISTANT_KIND,
    ApiToken,
    AuthSession,
    User,
    Workspace,
    WorkspaceMember,
    is_assistant,
    reserved_email,
)
from glasshaus.identity.schemas import (
    ApiTokenCreate,
    ApiTokenCreated,
    ApiTokenRead,
    PasswordChange,
    UserCreate,
    UserRead,
    UserUpdate,
    WorkspaceCreate,
    WorkspaceMemberRead,
    WorkspaceMemberSet,
    WorkspaceRead,
    WorkspaceUpdate,
)
from glasshaus.logs import get_logger
from glasshaus.models import Tenant

LOGIN_MAX_ATTEMPTS = 10
LOGIN_WINDOW_SECONDS = 900
# Per account across all addresses, so rotating (or spoofing) the client IP does not help guessing.
log = get_logger(__name__)
ACCOUNT_MAX_ATTEMPTS = 30
REUSE_GRACE = timedelta(seconds=30)


# --------------------------------------------------------------------------- authentication


@dataclass(frozen=True, slots=True)
class LoginResult:
    user: User
    access_token: str
    refresh_token: str
    session_id: uuid.UUID


async def _tenant_by_slug(session: AsyncSession, slug: str | None) -> Tenant:
    tenant = await session.scalar(
        select(Tenant).where(Tenant.slug == (slug or get_settings().default_tenant_slug))
    )
    if tenant is None:
        raise Unauthenticated("invalid credentials")
    return tenant


async def _check_login_rate(key: str, limit: int = LOGIN_MAX_ATTEMPTS) -> None:
    from glasshaus.redis_client import get_redis

    redis = get_redis()
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, LOGIN_WINDOW_SECONDS)
    if count > limit:
        raise RateLimited("too many login attempts; try again later")


async def _known_address(session: AsyncSession, user_id: uuid.UUID, ip: str) -> bool:
    """Whether this person has signed in from this address in the last 90 days."""
    since = datetime.now(UTC) - timedelta(days=90)
    found = await session.scalar(
        select(AuthSession.id)
        .where(AuthSession.user_id == user_id, AuthSession.ip == ip[:64], AuthSession.created_at >= since)
        .limit(1)
    )
    return found is not None


async def _issue_session(
    session: AsyncSession, user: User, *, user_agent: str, ip: str, family: uuid.UUID | None = None
) -> LoginResult:
    refresh = security.new_refresh_token()
    session_id = uuid.uuid4()
    auth_session = AuthSession(
        id=session_id,
        family_id=family or session_id,
        tenant_id=user.tenant_id,
        user_id=user.id,
        refresh_hash=security.sha256(refresh),
        expires_at=datetime.now(UTC) + security.REFRESH_TOKEN_TTL,
        user_agent=user_agent[:300],
        ip=ip[:64],
    )
    session.add(auth_session)
    access = security.create_access_token(
        user_id=user.id, tenant_id=user.tenant_id, org_role=user.org_role, session_id=auth_session.id
    )
    return LoginResult(user=user, access_token=access, refresh_token=refresh, session_id=auth_session.id)


async def login(
    session: AsyncSession, *, email: str, password: str, organization: str | None, user_agent: str, ip: str
) -> LoginResult:
    from glasshaus.audit.service import record_raw
    from glasshaus.redis_client import get_redis

    await _check_login_rate(f"glasshaus:login:{ip}:{email.lower()}")
    # Failures for this account from anywhere. Past the limit, only a correct password from an address
    # this person has signed in from before gets through: guessing from many addresses stops, but a
    # stranger can no longer lock the real person out by typing wrong passwords.
    account_key = f"glasshaus:login-account:{email.lower()}"
    locked = int(await get_redis().get(account_key) or 0) >= ACCOUNT_MAX_ATTEMPTS
    tenant = await _tenant_by_slug(session, organization)
    await apply_tenant(session, tenant.id)
    user = await session.scalar(select(User).where(func.lower(User.email) == email.lower()))
    detail = {"email": email.lower(), "ip": ip, "user_agent": user_agent[:200]}
    if not security.verify_password(user.password_hash if user else None, password) or user is None:
        failures = await get_redis().incr(account_key)
        if failures == 1:
            await get_redis().expire(account_key, LOGIN_WINDOW_SECONDS)
        await record_raw(
            tenant.id,
            "auth.login",
            outcome="denied",
            actor_id=user.id if user else None,
            method="session",
            detail={**detail, "reason": "invalid credentials"},
        )
        if locked or failures > ACCOUNT_MAX_ATTEMPTS:
            raise RateLimited("too many login attempts; try again later")
        raise Unauthenticated("invalid credentials")
    if locked and not await _known_address(session, user.id, ip):
        await record_raw(
            tenant.id,
            "auth.login",
            outcome="denied",
            actor_id=user.id,
            method="session",
            detail={**detail, "reason": "account locked; new address"},
        )
        raise RateLimited("too many login attempts; try again later")
    if not user.is_active or is_assistant(user):
        await record_raw(
            tenant.id,
            "auth.login",
            outcome="denied",
            actor_id=user.id,
            method="session",
            detail={**detail, "reason": "account disabled"},
        )
        raise Unauthenticated("account disabled")
    from glasshaus.sso.service import password_login_allowed

    if not await password_login_allowed(session, user):
        await record_raw(
            tenant.id,
            "auth.login",
            outcome="denied",
            actor_id=user.id,
            method="session",
            detail={**detail, "reason": "single sign-on required"},
        )
        raise Unauthenticated("this organization requires single sign-on")
    await record_raw(tenant.id, "auth.login", outcome="ok", actor_id=user.id, method="session", detail=detail)
    await get_redis().delete(account_key)
    if user.password_hash and security.needs_rehash(user.password_hash):
        user.password_hash = security.hash_password(password)
    user.last_login_at = datetime.now(UTC)
    return await _issue_session(session, user, user_agent=user_agent, ip=ip)


async def refresh(session: AsyncSession, refresh_token: str, *, user_agent: str, ip: str) -> LoginResult:
    """Rotate a refresh token. Reusing one that was rotated a while ago means it was copied: every
    session from that sign-in ends (a short grace covers two tabs refreshing at the same moment)."""
    now = datetime.now(UTC)
    current = await session.scalar(
        select(AuthSession)
        .where(AuthSession.refresh_hash == security.sha256(refresh_token))
        .with_for_update()
    )
    if current is not None and current.revoked_at is not None and now - current.revoked_at > REUSE_GRACE:
        from glasshaus.db import system_session

        family = current.family_id or current.id
        async with system_session() as own:  # its own transaction: it must outlive the error below
            await apply_tenant(own, current.tenant_id)
            await own.execute(
                update(AuthSession)
                .where(AuthSession.family_id == family, AuthSession.revoked_at.is_(None))
                .values(revoked_at=now)
            )
        log.warning("auth.refresh_reuse", user=str(current.user_id))
        raise Unauthenticated("session expired")
    if current is None or current.revoked_at is not None or current.expires_at <= now:
        raise Unauthenticated("session expired")
    await apply_tenant(session, current.tenant_id)
    user = await session.get(User, current.user_id)
    if user is None or not user.is_active:
        raise Unauthenticated("session expired")
    current.revoked_at = now
    return await _issue_session(
        session, user, user_agent=user_agent, ip=ip, family=current.family_id or current.id
    )


async def logout(session: AsyncSession, refresh_token: str) -> None:
    from glasshaus.audit.service import record_raw

    ended = (
        await session.execute(
            update(AuthSession)
            .where(
                AuthSession.refresh_hash == security.sha256(refresh_token), AuthSession.revoked_at.is_(None)
            )
            .values(revoked_at=datetime.now(UTC))
            .returning(AuthSession.tenant_id, AuthSession.user_id)
        )
    ).first()
    if ended is not None:
        await record_raw(
            ended.tenant_id, "auth.logout", outcome="ok", actor_id=ended.user_id, method="session"
        )


async def actor_from_access_token(session: AsyncSession, token: str) -> Actor:
    try:
        claims = security.decode_access_token(token)
        user_id, tenant_id, session_id = (
            uuid.UUID(claims["sub"]),
            uuid.UUID(claims["tid"]),
            uuid.UUID(claims["sid"]),
        )
    except (jwt.PyJWTError, ValueError, KeyError) as exc:
        raise Unauthenticated("invalid or expired token") from exc
    await apply_tenant(session, tenant_id)
    row = (
        await session.execute(
            select(User.org_role, User.is_active, User.kind, AuthSession.revoked_at)
            .join(AuthSession, AuthSession.user_id == User.id)
            .where(User.id == user_id, AuthSession.id == session_id)
        )
    ).one_or_none()
    if row is None or not row.is_active or row.revoked_at is not None or row.kind == ASSISTANT_KIND:
        raise Unauthenticated("session revoked")
    return Actor(tenant_id=tenant_id, user_id=user_id, org_role=row.org_role, method="session")


async def actor_from_api_token(session: AsyncSession, raw: str) -> Actor:
    if not raw.startswith(security.API_TOKEN_PREFIX):
        raise Unauthenticated("invalid token")
    now = datetime.now(UTC)
    token = await session.scalar(select(ApiToken).where(ApiToken.token_hash == security.sha256(raw)))
    if token is None or token.revoked_at is not None or (token.expires_at and token.expires_at <= now):
        raise Unauthenticated("invalid or expired token")
    await apply_tenant(session, token.tenant_id)
    user = await session.get(User, token.user_id)
    if user is None or not user.is_active or is_assistant(user):
        raise Unauthenticated("invalid or expired token")
    if token.last_used_at is None or now - token.last_used_at > timedelta(minutes=5):
        token.last_used_at = now
    return Actor(
        tenant_id=token.tenant_id,
        user_id=user.id,
        org_role=user.org_role,
        method="token",
        scopes=frozenset(token.scopes),
        client=f"token:{token.id}",
    )


# --------------------------------------------------------------------------- users


def _require_user(ctx: ServiceContext) -> uuid.UUID:
    if ctx.actor.user_id is None:
        raise PermissionDenied("a user principal is required")
    return ctx.actor.user_id


async def get_me(ctx: ServiceContext) -> UserRead:
    user = await ctx.session.get(User, _require_user(ctx))
    if user is None:
        raise NotFound("user not found")
    from glasshaus.people.service import direct_report_count

    return UserRead.model_validate(user).model_copy(
        update={"direct_reports": await direct_report_count(ctx.session, user.id)}
    )


async def change_password(ctx: ServiceContext, data: PasswordChange) -> None:
    if ctx.actor.method != "session":
        raise PermissionDenied("password changes require an interactive session")
    user = await ctx.session.get(User, _require_user(ctx))
    if user is None or not security.verify_password(user.password_hash, data.current_password):
        raise InvalidInput("current password is incorrect")
    from glasshaus.identity.passwords import password_problem

    if problem := password_problem(data.new_password, email=user.email):
        raise InvalidInput(problem)
    user.password_hash = security.hash_password(data.new_password)
    await ctx.session.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
    events.emit(ctx, "user.password_changed", "user", user.id, {"user_id": str(user.id)})


async def list_users(ctx: ServiceContext, *, q: str | None = None, limit: int = 100) -> list[UserRead]:
    if ctx.actor.org_role == OrgRole.GUEST:
        raise PermissionDenied("guests cannot list users")
    stmt = (
        select(User).where(User.kind != ASSISTANT_KIND).order_by(func.lower(User.name)).limit(min(limit, 500))
    )
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(func.lower(User.name).like(like) | func.lower(User.email).like(like))
    people = [UserRead.model_validate(u) for u in (await ctx.session.scalars(stmt)).all()]
    if not ctx.actor.is_org_admin:
        # When someone last signed in is account administration, not something colleagues need.
        for person in people:
            person.last_login_at = None
    return people


async def create_user(ctx: ServiceContext, data: UserCreate) -> UserRead:
    require_org(ctx, Permission.USER_MANAGE)
    if data.org_role == OrgRole.OWNER and ctx.actor.org_role != OrgRole.OWNER:
        raise PermissionDenied("only owners can create owners")
    if reserved_email(data.email):
        raise InvalidInput("this address is reserved for the project assistant")
    user = User(
        id=uuid.uuid4(),
        tenant_id=ctx.tenant_id,
        email=data.email,
        name=data.name,
        org_role=data.org_role,
        password_hash=security.hash_password(data.password) if data.password else None,
    )
    ctx.session.add(user)
    try:
        await ctx.session.flush()
    except IntegrityError as exc:
        raise Conflict("a user with this email already exists") from exc
    result = UserRead.model_validate(user)
    events.emit(ctx, "user.created", "user", user.id, result)
    return result


async def update_user(ctx: ServiceContext, user_id: uuid.UUID, data: UserUpdate) -> UserRead:
    require_org(ctx, Permission.USER_MANAGE)
    user = await ctx.session.get(User, user_id)
    if user is None:
        raise NotFound("user not found")
    if is_assistant(user):
        raise InvalidInput("the project assistant account is managed by Glasshaus")
    if user.erased_at is not None:
        raise InvalidInput("this person was erased; add them again as a new person if they return")
    changes = data.model_dump(exclude_unset=True)
    if OrgRole.OWNER in (user.org_role, changes.get("org_role")) and ctx.actor.org_role != OrgRole.OWNER:
        raise PermissionDenied("only owners can change owners")
    if user.id == ctx.actor.user_id and ("org_role" in changes or changes.get("is_active") is False):
        raise InvalidInput("you cannot change your own role or deactivate yourself")
    if (
        changes.get("org_role") in (OrgRole.OWNER, OrgRole.ADMIN)
        and changes["org_role"] != user.org_role
        and ctx.actor.method != "session"
    ):
        # Not through a token or an AI agent (text in a task could ask it to): a person does it here.
        raise PermissionDenied("make someone an admin or owner in Admin > People, signed in")
    for field, value in changes.items():
        setattr(user, field, value)
    await ctx.session.flush()
    if changes.get("is_active") is False:
        from glasshaus.governance.service import revoke_user_sessions

        await revoke_user_sessions(ctx, user.id)
    result = UserRead.model_validate(user)
    events.emit(
        ctx, "user.updated", "user", user.id, {"changes": changes, "user": result.model_dump(mode="json")}
    )
    return result


# --------------------------------------------------------------------------- workspaces


async def list_workspaces(ctx: ServiceContext) -> list[WorkspaceRead]:
    from glasshaus.core.authz import require_scope
    from glasshaus.projects.models import Project, ProjectMember

    require_scope(ctx, Permission.WORKSPACE_READ)
    stmt = select(Workspace).order_by(func.lower(Workspace.name))
    if not ctx.actor.is_org_admin:
        uid = ctx.actor.user_id
        member_of = select(WorkspaceMember.workspace_id).where(WorkspaceMember.user_id == uid)
        via_project = (
            select(Project.workspace_id)
            .join(ProjectMember, ProjectMember.project_id == Project.id)
            .where(ProjectMember.user_id == uid)
        )
        ids = via_project if ctx.actor.org_role == OrgRole.GUEST else member_of.union(via_project)
        stmt = stmt.where(Workspace.id.in_(ids))
    return [WorkspaceRead.model_validate(w) for w in (await ctx.session.scalars(stmt)).all()]


async def get_workspace(ctx: ServiceContext, workspace_id: uuid.UUID) -> WorkspaceRead:
    await require_workspace(ctx, workspace_id)
    workspace = await ctx.session.get(Workspace, workspace_id)
    if workspace is None:
        raise NotFound("workspace not found")
    return WorkspaceRead.model_validate(workspace)


async def create_workspace(ctx: ServiceContext, data: WorkspaceCreate) -> WorkspaceRead:
    if ctx.actor.org_role not in (OrgRole.OWNER, OrgRole.ADMIN, OrgRole.MEMBER):
        raise PermissionDenied("guests cannot create workspaces")
    from glasshaus.core.authz import require_scope

    require_scope(ctx, Permission.WORKSPACE_CREATE)
    workspace = Workspace(id=uuid.uuid4(), tenant_id=ctx.tenant_id, **data.model_dump())
    ctx.session.add(workspace)
    try:
        await ctx.session.flush()
    except IntegrityError as exc:
        raise Conflict("a workspace with this slug already exists") from exc
    if ctx.actor.user_id:
        ctx.session.add(
            WorkspaceMember(
                tenant_id=ctx.tenant_id,
                workspace_id=workspace.id,
                user_id=ctx.actor.user_id,
                role=WorkspaceRole.ADMIN,
            )
        )
    result = WorkspaceRead.model_validate(workspace)
    events.emit(ctx, "workspace.created", "workspace", workspace.id, result)
    return result


async def update_workspace(
    ctx: ServiceContext, workspace_id: uuid.UUID, data: WorkspaceUpdate
) -> WorkspaceRead:
    await require_workspace(ctx, workspace_id, manage=True)
    workspace = await ctx.session.get(Workspace, workspace_id)
    assert workspace is not None
    changes = data.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(workspace, field, value)
    await ctx.session.flush()
    result = WorkspaceRead.model_validate(workspace)
    events.emit(ctx, "workspace.updated", "workspace", workspace.id, {"changes": changes})
    return result


async def list_workspace_members(ctx: ServiceContext, workspace_id: uuid.UUID) -> list[WorkspaceMemberRead]:
    await require_workspace(ctx, workspace_id)
    rows = await ctx.session.scalars(
        select(WorkspaceMember).where(WorkspaceMember.workspace_id == workspace_id)
    )
    return [WorkspaceMemberRead.model_validate(m) for m in rows.all()]


async def set_workspace_member(
    ctx: ServiceContext, workspace_id: uuid.UUID, data: WorkspaceMemberSet
) -> WorkspaceMemberRead:
    await require_workspace(ctx, workspace_id, manage=True)
    person = await ctx.session.get(User, data.user_id)
    if person is None or is_assistant(person):
        raise NotFound("user not found")
    member = await ctx.session.get(WorkspaceMember, (workspace_id, data.user_id))
    if member is None:
        member = WorkspaceMember(
            tenant_id=ctx.tenant_id, workspace_id=workspace_id, user_id=data.user_id, role=data.role
        )
        ctx.session.add(member)
    else:
        member.role = data.role
    await ctx.session.flush()
    events.emit(ctx, "workspace.member_set", "workspace", workspace_id, data)
    return WorkspaceMemberRead.model_validate(member)


async def remove_workspace_member(ctx: ServiceContext, workspace_id: uuid.UUID, user_id: uuid.UUID) -> None:
    await require_workspace(ctx, workspace_id, manage=True)
    member = await ctx.session.get(WorkspaceMember, (workspace_id, user_id))
    if member is None:
        raise NotFound("member not found")
    await ctx.session.delete(member)
    events.emit(ctx, "workspace.member_removed", "workspace", workspace_id, {"user_id": str(user_id)})


# --------------------------------------------------------------------------- API tokens


async def create_api_token(ctx: ServiceContext, data: ApiTokenCreate) -> ApiTokenCreated:
    user_id = _require_user(ctx)
    if ctx.actor.scopes is not None and not set(data.scopes) <= ctx.actor.scopes | {Scope.READ}:
        raise PermissionDenied("a token cannot mint a token with broader scopes")
    if Scope.ADMIN in data.scopes and not ctx.actor.is_org_admin:
        raise PermissionDenied("only organization admins can create admin-scoped tokens")
    raw, prefix = security.new_api_token()
    token = ApiToken(
        id=uuid.uuid4(),
        tenant_id=ctx.tenant_id,
        user_id=user_id,
        name=data.name,
        prefix=prefix,
        token_hash=security.sha256(raw),
        scopes=[s.value for s in data.scopes],
        expires_at=datetime.now(UTC) + timedelta(days=data.expires_in_days) if data.expires_in_days else None,
    )
    ctx.session.add(token)
    await ctx.session.flush()
    await ctx.session.refresh(token)
    events.emit(ctx, "api_token.created", "api_token", token.id, {"name": token.name, "scopes": token.scopes})
    return ApiTokenCreated(**ApiTokenRead.model_validate(token).model_dump(), token=raw)


async def list_api_tokens(ctx: ServiceContext) -> list[ApiTokenRead]:
    user_id = _require_user(ctx)
    rows = await ctx.session.scalars(
        select(ApiToken)
        .where(ApiToken.tenant_id == ctx.tenant_id, ApiToken.user_id == user_id)
        .order_by(ApiToken.created_at.desc())
    )
    return [ApiTokenRead.model_validate(t) for t in rows.all()]


async def revoke_api_token(ctx: ServiceContext, token_id: uuid.UUID) -> None:
    user_id = _require_user(ctx)
    token = await ctx.session.scalar(
        select(ApiToken).where(ApiToken.id == token_id, ApiToken.tenant_id == ctx.tenant_id)
    )
    if token is None or (token.user_id != user_id and not ctx.actor.is_org_admin):
        raise NotFound("token not found")
    if token.revoked_at is None:
        token.revoked_at = datetime.now(UTC)
        events.emit(ctx, "api_token.revoked", "api_token", token.id, {"name": token.name})


# --------------------------------------------------------------------------- bootstrap


async def ensure_owner(
    session: AsyncSession, tenant: Tenant, *, email: str, password: str, name: str
) -> User:
    """Create the first owner if the tenant has no users (idempotent)."""
    await apply_tenant(session, tenant.id)
    existing = await session.scalar(select(User).where(User.tenant_id == tenant.id).limit(1))
    if existing is not None:
        return existing
    user = User(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        email=email,
        name=name,
        org_role=OrgRole.OWNER,
        password_hash=security.hash_password(password),
    )
    session.add(user)
    await session.flush()
    return user
