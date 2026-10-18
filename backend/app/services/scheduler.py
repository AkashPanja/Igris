from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.models import Connection, User
from app.services import connections as svc
from app.services.brokers import fyers as fyers_broker
from app.services.brokers import groww as groww_broker

log = logging.getLogger("igris.scheduler")

REAUTH_WINDOW_MINUTES = 5  # tolerate tick jitter around the scheduled time


def _local_now() -> datetime:
    return datetime.now().astimezone()


async def _send_reauth_email(session, user: User, conn: Connection, reason: str) -> None:
    from app.services.auth import get_setting
    from app.services.email import send_email

    smtp_host = await get_setting(session, "smtp_host")
    if not smtp_host or not user.email:
        return
    base = settings.public_base_url.strip().rstrip("/") or ""
    link = f"{base}/connections" if base else "/connections"
    if conn.provider == "fyers":
        body = (
            f"Hi,\n\nYour Fyers connection \"{conn.label}\" needs to be re-authorized.\n"
            f"Reason: {reason}\n\n"
            f"Open {link}, click Re-authorize on the Fyers card and complete the OAuth flow.\n\n"
            "— Igris"
        )
        subject = f"[Igris] Re-authorize Fyers: {conn.label}"
    else:
        body = (
            f"Hi,\n\nAutomatic login for your Groww connection \"{conn.label}\" failed.\n"
            f"Reason: {reason}\n\n"
            f"Open {link}, check the TOTP secret and press Connect again.\n\n"
            "— Igris"
        )
        subject = f"[Igris] Groww login failed: {conn.label}"
    try:
        await send_email(
            host=smtp_host,
            port=int(await get_setting(session, "smtp_port") or 587),
            security=await get_setting(session, "smtp_security") or "STARTTLS",
            username=await get_setting(session, "smtp_username") or "",
            password_encrypted=await get_setting(session, "smtp_password") or "",
            from_name=await get_setting(session, "smtp_from_name") or "Igris",
            from_email=await get_setting(session, "smtp_from_email") or "",
            to_email=user.email,
            subject=subject,
            body=body,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("reauth email failed for conn %s: %s", conn.id, exc)


def _due_for_reauth(conn: Connection) -> bool:
    """True when local time has passed today's reauth_time and we haven't run today."""
    now = _local_now()
    scheduled = conn.reauth_time or settings.default_reauth_time
    try:
        hh, mm = scheduled.split(":")
        target = now.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
    except (ValueError, AttributeError):
        return False
    last = conn.last_reauth_at
    if last is not None:
        last_local = last.astimezone() if last.tzinfo else last.replace(tzinfo=timezone.utc).astimezone()
        if last_local.date() == now.date():
            return False
    # Don't fire before the scheduled time (allow small window after)
    return now >= target


async def _reauth(session, conn: Connection, user: User) -> None:
    creds = svc.load_credentials(conn)
    if conn.provider == "groww":
        try:
            result = await groww_broker.connect(conn.app_id, creds.get("totp_secret", ""))
        except Exception as exc:  # noqa: BLE001
            conn.status = "error"
            conn.last_error = str(exc)
            await session.commit()
            log.warning("groww auto-reauth failed for %s: %s", conn.id, exc)
            await _send_reauth_email(session, user, conn, str(exc))
            return
        creds["access_token"] = result["access_token"]
        svc.save_credentials(conn, creds)
        conn.status = "connected"
        conn.expires_at = result["expires_at"]
        conn.last_error = ""
        conn.last_reauth_at = datetime.now(timezone.utc)
        await session.commit()
        log.info("groww auto-reauth ok for %s", conn.id)
    else:  # fyers needs interactive OAuth — notify instead
        expires = conn.expires_at
        expired = expires is not None and expires <= datetime.now(timezone.utc)
        conn.last_reauth_at = datetime.now(timezone.utc)
        if expired:
            conn.status = "needs_auth"
            conn.last_error = "Access token expired — re-authorize"
            await session.commit()
        await _send_reauth_email(
            session,
            user,
            conn,
            f"access token expires {expires.isoformat() if expires else 'soon'}",
        )


async def _agent_tick(session) -> None:
    """S4: paper monitor (stop/target/EOD) + interval jobs for each user."""
    from datetime import timedelta

    from app.models import CronJob, Rule, User as UserModel
    from app.services.agent import tools as agent_tools
    from app.services.agent import trading as agent_trading

    users = (await session.execute(select(UserModel).where(UserModel.is_active == True))).scalars()  # noqa: E712
    now = datetime.now(timezone.utc)
    for user in users:
        rule = await session.get(Rule, user.id)
        if not rule:
            continue
        try:
            await agent_trading.monitor_tick(session, user, rule)
            await session.commit()
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            log.warning("monitor tick failed for user %s: %s", user.id, exc)
        # interval jobs
        jobs = (await session.execute(
            select(CronJob).where(CronJob.user_id == user.id, CronJob.enabled == True)  # noqa: E712
        )).scalars()
        for job in jobs:
            if job.market_hours_only and not agent_trading.is_market_hours():
                continue
            last = job.last_run_at
            if last is not None and now - last < timedelta(minutes=job.interval_minutes):
                continue
            try:
                result = await agent_tools.execute_tool(
                    session, user, job.tool_name, __import__("json").loads(job.args or "{}")
                )
                job.last_run_at = now
                job.last_result = str(result)[:2000]
                await session.commit()
                log.info("job %s ran: %s", job.id, job.tool_name)
            except Exception as exc:  # noqa: BLE001
                await session.rollback()
                job.last_result = f"error: {exc}"[:500]
                await session.commit()
                log.warning("job %s failed: %s", job.id, exc)


async def tick() -> None:
    async with SessionLocal() as session:
        result = await session.execute(
            select(Connection, User)
            .join(User, User.id == Connection.user_id)
            .where(Connection.status.in_(("connected", "needs_auth")))
        )
        rows = list(result.all())
        now_utc = datetime.now(timezone.utc)
        for conn, user in rows:
            # Expire tracking (independent of reauth time)
            if conn.status == "connected" and conn.expires_at and conn.expires_at <= now_utc:
                conn.status = "needs_auth"
                conn.last_error = "Access token expired — re-authorize"
                await session.commit()
                await _send_reauth_email(session, user, conn, "access token expired")
                continue
            if conn.status == "needs_auth":
                # only re-evaluate via explicit reauth; keep waiting for user
                continue
            if _due_for_reauth(conn):
                await _reauth(session, conn, user)
    async with SessionLocal() as session:
        await _agent_tick(session)


async def run_forever() -> None:
    log.info("scheduler started (reauth default %s)", settings.default_reauth_time)
    while True:
        try:
            await tick()
        except Exception as exc:  # noqa: BLE001
            log.warning("scheduler tick failed: %s", exc)
        await asyncio.sleep(60)


def start() -> asyncio.Task:
    return asyncio.create_task(run_forever())
