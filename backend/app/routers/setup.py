from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_session
from app.models import User
from app.schemas import (
    Message,
    SessionOut,
    SetupFinish,
    SetupState,
    SetupStep1,
    SetupStep2,
    SetupStep3,
    SmtpTestResult,
    UserOut,
)
from app.services import auth as auth_service
from app.services.email import send_email
from app.utils.crypto import encrypt

router = APIRouter()


async def _ensure_not_installed(session: AsyncSession) -> None:
    if await auth_service.is_installed(session):
        raise HTTPException(status_code=404, detail="Not found")


@router.get("/state", response_model=SetupState)
async def setup_state(session: AsyncSession = Depends(get_session)) -> SetupState:
    installed = await auth_service.is_installed(session)
    if installed:
        raise HTTPException(status_code=404, detail="Not found")
    smtp_host = await auth_service.get_setting(session, "smtp_host")
    return SetupState(
        installed=False,
        setup_token_required=bool(settings.setup_token),
        smtp_configured=bool(smtp_host),
    )


@router.post("/step1")
async def setup_step1(
    body: SetupStep1, session: AsyncSession = Depends(get_session)
) -> Message:
    await _ensure_not_installed(session)
    if settings.setup_token and body.setup_token != settings.setup_token:
        raise HTTPException(status_code=403, detail="Invalid setup token")
    await auth_service.set_setting(session, "app_name", body.app_name)
    return Message(detail="ok")


@router.post("/step2", response_model=UserOut)
async def setup_step2(
    body: SetupStep2, session: AsyncSession = Depends(get_session)
) -> UserOut:
    await _ensure_not_installed(session)
    if body.password != body.confirm_password:
        raise HTTPException(status_code=422, detail="Passwords do not match")
    result = await session.execute(
        select(User).where((User.username == body.username) | (User.email == body.email))
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Username or email already exists")
    user = await auth_service.create_user(
        session, body.username, body.email, body.password
    )
    return UserOut.model_validate(user)


@router.post("/smtp-test", response_model=SmtpTestResult)
async def smtp_test(
    body: SetupStep3, session: AsyncSession = Depends(get_session)
) -> SmtpTestResult:
    await _ensure_not_installed(session)
    if not body.host or not body.from_email:
        return SmtpTestResult(success=False, message="Host and from-email required")
    try:
        await send_email(
            host=body.host,
            port=body.port,
            security=body.security,
            username=body.username,
            password_encrypted=encrypt(body.password),
            from_name=body.from_name,
            from_email=body.from_email,
            to_email=body.from_email,
            subject="Igris SMTP test",
            body="If you can read this, SMTP is configured correctly.",
        )
        return SmtpTestResult(success=True, message="Test email sent")
    except Exception as exc:  # noqa: BLE001 — surface real error
        return SmtpTestResult(success=False, message=str(exc))


@router.post("/finish", response_model=SessionOut)
async def setup_finish(
    body: SetupFinish,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> SessionOut:
    await _ensure_not_installed(session)

    result = await session.execute(select(User).order_by(User.id).limit(1))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=400, detail="Complete step 2 first")

    if body.smtp and body.smtp.host:
        await auth_service.set_setting(session, "smtp_host", body.smtp.host)
        await auth_service.set_setting(session, "smtp_port", str(body.smtp.port))
        await auth_service.set_setting(session, "smtp_security", body.smtp.security)
        await auth_service.set_setting(session, "smtp_username", body.smtp.username)
        await auth_service.set_setting(
            session, "smtp_password", encrypt(body.smtp.password)
        )
        await auth_service.set_setting(session, "smtp_from_name", body.smtp.from_name)
        await auth_service.set_setting(session, "smtp_from_email", body.smtp.from_email)

    await auth_service.set_setting(session, "installed", "true")

    sess = await auth_service.create_session(session, user.id)
    response.set_cookie(
        settings.session_cookie_name,
        sess.id,
        httponly=True,
        samesite="lax",
        max_age=settings.session_ttl_hours * 3600,
        path="/",
    )
    response.set_cookie(
        settings.csrf_cookie_name,
        sess.csrf_token,
        httponly=False,
        samesite="lax",
        max_age=settings.session_ttl_hours * 3600,
        path="/",
    )
    return SessionOut(user=UserOut.model_validate(user), csrf_token=sess.csrf_token)
