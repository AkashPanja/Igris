from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.config import settings

# Fyers access tokens expire daily at 06:30 AM IST
FYERS_TOKEN_EXPIRE_H, FYERS_TOKEN_EXPIRE_M = 6, 30
IST = timezone(timedelta(hours=5, minutes=30))


def next_token_expiry(now: datetime | None = None) -> datetime:
    """UTC time of the next 06:30 AM IST — when Fyers kills the access token."""
    now_ist = (now or datetime.now(timezone.utc)).astimezone(IST)
    target = now_ist.replace(
        hour=FYERS_TOKEN_EXPIRE_H, minute=FYERS_TOKEN_EXPIRE_M, second=0, microsecond=0
    )
    if now_ist >= target:
        target += timedelta(days=1)
    return target.astimezone(timezone.utc)


def is_manual_flow() -> bool:
    """True when there is no usable public base URL (localhost / empty)."""
    base = (settings.public_base_url or "").strip().rstrip("/")
    if not base or base.lower() in ("none", "off"):
        return True
    lowered = base.lower()
    return "localhost" in lowered or "127.0.0.1" in lowered


def redirect_uri() -> str:
    base = settings.public_base_url.strip().rstrip("/")
    return f"{base}/api/connections/fyers/callback"


def build_auth_url(conn_id: str, app_id: str) -> str:
    from fyers_apiv3.fyersModel import SessionModel

    session = SessionModel(
        client_id=app_id,
        redirect_uri=redirect_uri(),
        response_type="code",
        grant_type="authorization_code",
        state=conn_id,
    )
    return session.generate_authcode()


async def exchange_code(app_id: str, app_secret: str, auth_code: str) -> dict:
    """Exchange auth code for access token. Returns {access_token, expires_at}."""
    from fyers_apiv3.fyersModel import SessionModel

    session = SessionModel(
        client_id=app_id,
        secret_key=app_secret,
        grant_type="authorization_code",
        response_type="code",
        redirect_uri=redirect_uri(),
    )
    session.set_token(auth_code)
    result = session.generate_token()
    if not isinstance(result, dict):
        raise RuntimeError("Unexpected Fyers token response")
    if result.get("s") != "ok" and "access_token" not in result:
        raise RuntimeError(result.get("message") or str(result))
    token = result.get("access_token")
    if not token:
        raise RuntimeError("Fyers did not return access token")
    # Per docs: tokens expire daily at 06:30 AM IST
    return {"access_token": token, "expires_at": next_token_expiry()}


def client(app_id: str, access_token: str):
    from fyers_apiv3.fyersModel import FyersModel

    return FyersModel(client_id=app_id, token=access_token)


async def test_connection(app_id: str, access_token: str) -> tuple[bool, str]:
    import time

    if not access_token:
        return False, "Not authenticated yet"
    start = time.monotonic()
    try:
        resp = client(app_id, access_token).get_profile()
        ms = int((time.monotonic() - start) * 1000)
        if isinstance(resp, dict) and resp.get("s") == "ok":
            return True, f"OK · {ms}ms"
        msg = (resp or {}).get("message") if isinstance(resp, dict) else str(resp)
        return False, msg or "Fyers API error"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)
