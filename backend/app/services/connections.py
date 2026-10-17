from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Connection, User
from app.utils.crypto import decrypt, encrypt

PROVIDERS = ("fyers", "groww")

TOOLS: dict[str, list[str]] = {
    "fyers": [
        "get_profile",
        "get_quotes",
        "get_positions",
        "get_holdings",
        "get_orderbook",
        "get_funds",
        "get_market_status",
        "place_order",
        "cancel_order",
    ],
    "groww": [
        "get_profile",
        "get_quotes",
        "get_ltp",
        "get_holdings",
        "get_positions",
        "get_orderbook",
        "get_funds",
        "place_order",
        "cancel_order",
    ],
}

# Help content shown in the UI
PROVIDER_HELP = {
    "fyers": {
        "title": "How to get Fyers App ID & Secret",
        "url": "https://api-dashboard.fyers.in/",
        "url_label": "Fyers API Dashboard (My Apps)",
        "steps": [
            "Sign up / log in at fyers.in",
            "Open the Fyers API Dashboard (link above)",
            "Create a new app: set any name and the redirect URL {redirect}",
            "Copy the App ID (client_id) and Secret Key",
            "Paste them below, then Continue to OAuth",
        ],
    },
    "groww": {
        "title": "How to get Groww API Key & TOTP secret",
        "url": "https://groww.in/finance-api",
        "url_label": "Groww Finance API page",
        "steps": [
            "Log in to groww.in and open the Finance API page (link above)",
            "Enable API access for your account",
            "Copy the API Key",
            "Copy the TOTP secret (used for daily auto-login)",
            "Paste them below and press Connect",
        ],
    },
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def load_credentials(conn: Connection) -> dict:
    if not conn.credentials:
        return {}
    try:
        return json.loads(decrypt(conn.credentials)) or {}
    except (json.JSONDecodeError, ValueError):
        return {}


def save_credentials(conn: Connection, creds: dict) -> None:
    conn.credentials = encrypt(json.dumps(creds)) if creds else ""


def public_view(conn: Connection, user: User | None = None) -> dict:
    from app.config import settings

    return {
        "id": conn.id,
        "provider": conn.provider,
        "label": conn.label,
        "app_id": conn.app_id,
        "status": conn.status,
        "expires_at": conn.expires_at.isoformat() if conn.expires_at else None,
        "reauth_time": conn.reauth_time or settings.default_reauth_time,
        "last_error": conn.last_error,
        "last_reauth_at": conn.last_reauth_at.isoformat() if conn.last_reauth_at else None,
        "tools": TOOLS.get(conn.provider, []),
        "user_email": user.email if user else "",
    }


async def list_connections(session: AsyncSession, user_id: int) -> list[Connection]:
    result = await session.execute(
        select(Connection)
        .where(Connection.user_id == user_id)
        .order_by(Connection.created_at)
    )
    return list(result.scalars())


async def get_connection(
    session: AsyncSession, user_id: int, conn_id: str
) -> Connection | None:
    conn = await session.get(Connection, conn_id)
    if not conn or conn.user_id != user_id:
        return None
    return conn


async def create_connection(
    session: AsyncSession,
    user_id: int,
    provider: str,
    label: str,
    app_id: str,
    secrets: dict,
) -> Connection:
    from app.config import settings

    conn = Connection(
        id=secrets_token(),
        user_id=user_id,
        provider=provider,
        label=label or f"{provider.title()} connection",
        app_id=app_id,
        reauth_time=settings.default_reauth_time,
    )
    save_credentials(conn, secrets)
    session.add(conn)
    await session.commit()
    await session.refresh(conn)
    return conn


async def delete_connection(session: AsyncSession, conn: Connection) -> None:
    await session.delete(conn)
    await session.commit()


def secrets_token() -> str:
    return secrets.token_urlsafe(24)
