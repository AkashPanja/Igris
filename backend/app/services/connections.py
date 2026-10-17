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
        "title": "How to get Groww TOTP Token & QR Code",
        "url": "https://groww.in/trade-api/docs",
        "url_label": "Groww Trading API docs",
        "steps": [
            "Log in to groww.in → profile → Trading APIs, or open the Groww Cloud API Keys page",
            "Open the 'Generate API key' dropdown → choose 'Generate TOTP token', name it, Continue",
            "Copy the TOTP Token and paste it below",
            "Copy the TOTP QR Code text shown next to it and paste it below",
            "Press Connect — Igris generates the daily codes from the QR code automatically",
        ],
    },
}

_BASE32_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567=")


def normalize_base32(value: str) -> str:
    return "".join(value.split()).upper()


def extract_totp_secret(text: str) -> str:
    """Accept a base32 secret OR QR payload (otpauth:// URL) and return the base32 secret."""
    raw = (text or "").strip()
    if not raw:
        return ""
    if "otpauth://" in raw.lower():
        from urllib.parse import parse_qs, urlparse

        parsed = urlparse(raw)
        qs = parse_qs(parsed.query)
        secret = (qs.get("secret") or [""])[0]
        raw = secret
    secret = normalize_base32(raw)
    if not secret or not set(secret) <= _BASE32_CHARS or len(secret) < 16:
        raise ValueError("TOTP secret is not valid base32 (check the QR/secret)")
    return secret


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


def mask_secret(value: str) -> str:
    """Never expose full credential material in API responses / UI."""
    v = (value or "").strip()
    if not v:
        return ""
    if len(v) <= 10:
        return "••••••"
    return f"{v[:6]}…{v[-4:]}"


def public_view(conn: Connection, user: User | None = None) -> dict:
    from app.config import settings

    return {
        "id": conn.id,
        "provider": conn.provider,
        "label": conn.label,
        "app_id": mask_secret(conn.app_id),
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
