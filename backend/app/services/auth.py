from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import LoginAttempt, ResetToken, Session, Setting, User
from app.utils.passwords import hash_password, verify_password


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def is_installed(session: AsyncSession) -> bool:
    row = await session.get(Setting, "installed")
    return bool(row and row.value == "true")


async def get_setting(session: AsyncSession, key: str) -> str:
    row = await session.get(Setting, key)
    return row.value if row else ""


async def set_setting(session: AsyncSession, key: str, value: str) -> None:
    row = await session.get(Setting, key)
    if row:
        row.value = value
    else:
        session.add(Setting(key=key, value=value))
    await session.commit()


async def create_session(session: AsyncSession, user_id: int) -> Session:
    sid = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(32)
    expires = utcnow() + timedelta(hours=settings.session_ttl_hours)
    sess = Session(id=sid, user_id=user_id, csrf_token=csrf, expires_at=expires)
    session.add(sess)
    await session.commit()
    await session.refresh(sess)
    return sess


async def get_session_user(session: AsyncSession, sid: str) -> tuple[User, Session] | None:
    if not sid:
        return None
    sess = await session.get(Session, sid)
    if not sess:
        return None
    exp = sess.expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if exp < utcnow():
        await session.delete(sess)
        await session.commit()
        return None
    user = await session.get(User, sess.user_id)
    if not user or not user.is_active:
        return None
    return user, sess


async def delete_session(session: AsyncSession, sid: str) -> None:
    await session.execute(delete(Session).where(Session.id == sid))
    await session.commit()


async def count_recent_failures(session: AsyncSession, username: str) -> int:
    since = utcnow() - timedelta(minutes=settings.login_lockout_minutes)
    result = await session.execute(
        select(func.count())
        .select_from(LoginAttempt)
        .where(
            LoginAttempt.username == username,
            LoginAttempt.success.is_(False),
            LoginAttempt.created_at >= since,
        )
    )
    return result.scalar() or 0


async def record_attempt(session: AsyncSession, username: str, success: bool) -> None:
    session.add(LoginAttempt(username=username, success=success))
    await session.commit()


async def authenticate(
    session: AsyncSession, username_or_email: str, password: str
) -> User | None:
    result = await session.execute(
        select(User).where(
            (User.username == username_or_email) | (User.email == username_or_email)
        )
    )
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        return None
    if not verify_password(user.password_hash, password):
        return None
    return user


async def create_user(
    session: AsyncSession, username: str, email: str, password: str
) -> User:
    user = User(
        username=username,
        email=email,
        password_hash=hash_password(password),
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def create_reset_token(session: AsyncSession, user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    expires = utcnow() + timedelta(minutes=settings.reset_token_ttl_minutes)
    rt = ResetToken(id=token, user_id=user_id, expires_at=expires)
    session.add(rt)
    await session.commit()
    return token


async def consume_reset_token(session: AsyncSession, token: str) -> User | None:
    rt = await session.get(ResetToken, token)
    if not rt or rt.used:
        return None
    exp = rt.expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if exp < utcnow():
        return None
    rt.used = True
    await session.commit()
    return await session.get(User, rt.user_id)
