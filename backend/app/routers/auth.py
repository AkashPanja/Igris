from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_session
from app.models import User
from app.schemas import (
    ForgotPasswordRequest,
    LoginRequest,
    Message,
    ResetPasswordRequest,
    SessionOut,
    UserOut,
)
from app.services import auth as auth_service
from app.services.email import send_email
from app.utils.passwords import hash_password

router = APIRouter()


def _set_session_cookies(response: Response, sid: str, csrf: str) -> None:
    response.set_cookie(
        settings.session_cookie_name,
        sid,
        httponly=True,
        samesite="lax",
        max_age=settings.session_ttl_hours * 3600,
        path="/",
    )
    response.set_cookie(
        settings.csrf_cookie_name,
        csrf,
        httponly=False,
        samesite="lax",
        max_age=settings.session_ttl_hours * 3600,
        path="/",
    )


def _clear_session_cookies(response: Response) -> None:
    response.delete_cookie(settings.session_cookie_name, path="/")
    response.delete_cookie(settings.csrf_cookie_name, path="/")


@router.post("/login", response_model=SessionOut)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> SessionOut:
    if not await auth_service.is_installed(session):
        raise HTTPException(status_code=400, detail="App not installed")

    key = body.username_or_email
    failures = await auth_service.count_recent_failures(session, key)
    if failures >= settings.login_max_failures:
        raise HTTPException(
            status_code=429,
            detail="Too many failed attempts. Try again later.",
        )

    user = await auth_service.authenticate(session, key, body.password)
    if not user:
        await auth_service.record_attempt(session, key, False)
        raise HTTPException(status_code=401, detail="Invalid credentials")

    await auth_service.record_attempt(session, key, True)
    sess = await auth_service.create_session(session, user.id)
    _set_session_cookies(response, sess.id, sess.csrf_token)
    return SessionOut(user=UserOut.model_validate(user), csrf_token=sess.csrf_token)


@router.post("/logout")
async def logout(
    request: Request, response: Response, session: AsyncSession = Depends(get_session)
) -> Message:
    sid = request.cookies.get(settings.session_cookie_name, "")
    if sid:
        await auth_service.delete_session(session, sid)
    _clear_session_cookies(response)
    return Message(detail="logged out")


@router.get("/me", response_model=SessionOut)
async def me(request: Request, session: AsyncSession = Depends(get_session)) -> SessionOut:
    sid = request.cookies.get(settings.session_cookie_name, "")
    result = await auth_service.get_session_user(session, sid)
    if not result:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user, sess = result
    return SessionOut(user=UserOut.model_validate(user), csrf_token=sess.csrf_token)


@router.post("/forgot-password")
async def forgot_password(
    body: ForgotPasswordRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> Message:
    if not await auth_service.is_installed(session):
        raise HTTPException(status_code=400, detail="App not installed")

    smtp_host = await auth_service.get_setting(session, "smtp_host")
    if not smtp_host:
        raise HTTPException(status_code=400, detail="Password reset not available")

    result = await session.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()
    if user:
        token = await auth_service.create_reset_token(session, user.id)
        port = int(await auth_service.get_setting(session, "smtp_port") or 587)
        security = await auth_service.get_setting(session, "smtp_security") or "STARTTLS"
        username = await auth_service.get_setting(session, "smtp_username")
        password = await auth_service.get_setting(session, "smtp_password")
        from_name = await auth_service.get_setting(session, "smtp_from_name") or "Igris"
        from_email = await auth_service.get_setting(session, "smtp_from_email")
        base_url = str(request.base_url).rstrip("/")
        reset_url = f"{base_url}/reset-password?token={token}"
        try:
            await send_email(
                host=smtp_host,
                port=port,
                security=security,
                username=username,
                password_encrypted=password,
                from_name=from_name,
                from_email=from_email,
                to_email=body.email,
                subject="Reset your Igris password",
                body=(
                    "Click the link below to reset your password "
                    f"(valid for {settings.reset_token_ttl_minutes} minutes):\n\n{reset_url}"
                ),
            )
        except Exception:
            pass
    return Message(detail="If that email is registered, a reset link has been sent")


@router.post("/reset-password")
async def reset_password(
    body: ResetPasswordRequest, session: AsyncSession = Depends(get_session)
) -> Message:
    if not await auth_service.is_installed(session):
        raise HTTPException(status_code=400, detail="App not installed")
    if body.password != body.confirm_password:
        raise HTTPException(status_code=422, detail="Passwords do not match")
    user = await auth_service.consume_reset_token(session, body.token)
    if not user:
        raise HTTPException(status_code=400, detail="Invalid or expired token")

    user.password_hash = hash_password(body.password)
    await session.commit()
    return Message(detail="Password updated")
