from __future__ import annotations

from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))


def generate_totp(totp_secret: str) -> str:
    import pyotp

    return pyotp.TOTP(totp_secret.strip()).now()


def next_token_expiry(now: datetime | None = None) -> datetime:
    """Groww access tokens die daily at 06:00 AM IST (docs), not 24h after issue."""
    now_utc = (now or datetime.now(timezone.utc))
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    t = now_utc.astimezone(IST)
    target = t.replace(hour=6, minute=0, second=0, microsecond=0)
    if target <= t:
        target += timedelta(days=1)
    return target.astimezone(timezone.utc)


async def connect(api_key: str, totp_secret: str) -> dict:
    """Login with TOTP, return {access_token, expires_at}."""
    from growwapi import GrowwAPI

    totp = generate_totp(totp_secret)
    token = GrowwAPI.get_access_token(api_key=api_key, totp=totp)
    if not token:
        raise RuntimeError("Groww did not return access token")
    return {"access_token": token, "expires_at": next_token_expiry()}


def client(access_token: str):
    from growwapi import GrowwAPI

    return GrowwAPI(access_token)


async def test_connection(access_token: str) -> tuple[bool, str]:
    import time

    if not access_token:
        return False, "Not authenticated yet"
    start = time.monotonic()
    try:
        groww = client(access_token)
        # SDK raises GrowwAPIException on FAILURE; payload returned on success
        groww.get_user_profile()
        ms = int((time.monotonic() - start) * 1000)
        return True, f"OK · {ms}ms"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)
