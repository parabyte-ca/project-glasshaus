from fastapi import APIRouter, Request, Response, status

from glasshaus.api.deps import ACCESS_COOKIE, CSRF_COOKIE, REFRESH_COOKIE, Ctx, Session, client_ip
from glasshaus.config import get_settings
from glasshaus.core.errors import Unauthenticated
from glasshaus.identity import security
from glasshaus.identity import service as identity
from glasshaus.identity.schemas import LoginRequest, PasswordChange, UserRead

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_cookies(response: Response, result: identity.LoginResult) -> None:
    secure = get_settings().public_url.startswith("https://")
    response.set_cookie(
        ACCESS_COOKIE,
        result.access_token,
        max_age=int(security.ACCESS_TOKEN_TTL.total_seconds()),
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        REFRESH_COOKIE,
        result.refresh_token,
        max_age=int(security.REFRESH_TOKEN_TTL.total_seconds()),
        httponly=True,
        secure=secure,
        samesite="strict",
        path="/api/v1/auth",
    )
    response.set_cookie(
        CSRF_COOKIE,
        security.new_csrf_token(),
        max_age=int(security.REFRESH_TOKEN_TTL.total_seconds()),
        httponly=False,
        secure=secure,
        samesite="strict",
        path="/",
    )


def _clear_cookies(response: Response) -> None:
    response.delete_cookie(ACCESS_COOKIE, path="/")
    response.delete_cookie(REFRESH_COOKIE, path="/api/v1/auth")
    response.delete_cookie(CSRF_COOKIE, path="/")


@router.post(
    "/login", response_model=UserRead, summary="Sign in with email and password (sets session cookies)"
)
async def login(body: LoginRequest, request: Request, response: Response, session: Session) -> UserRead:
    result = await identity.login(
        session,
        email=body.email,
        password=body.password,
        organization=body.organization,
        user_agent=request.headers.get("user-agent", ""),
        ip=client_ip(request),
    )
    _set_cookies(response, result)
    return UserRead.model_validate(result.user)


@router.post("/refresh", response_model=UserRead, summary="Rotate the session using the refresh cookie")
async def refresh_session(request: Request, response: Response, session: Session) -> UserRead:
    token = request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise Unauthenticated("no session")
    result = await identity.refresh(
        session, token, user_agent=request.headers.get("user-agent", ""), ip=client_ip(request)
    )
    _set_cookies(response, result)
    return UserRead.model_validate(result.user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="End the session")
async def logout(request: Request, response: Response, session: Session) -> None:
    token = request.cookies.get(REFRESH_COOKIE)
    if token:
        await identity.logout(session, token)
    _clear_cookies(response)


@router.post(
    "/password", status_code=status.HTTP_204_NO_CONTENT, summary="Change your password (ends sessions)"
)
async def change_password(body: PasswordChange, ctx: Ctx, response: Response) -> None:
    await identity.change_password(ctx, body)
    _clear_cookies(response)
