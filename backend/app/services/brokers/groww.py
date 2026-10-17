from __future__ import annotations

from datetime import datetime, timedelta, timezone


def generate_totp(totp_secret: str) -> str:
    import pyotp

    return pyotp.TOTP(totp_secret.strip()).now()


async def connect(api_key: str, totp_secret: str) -> dict:
    """Login with TOTP, return {access_token, expires_at}."""
    from growwapi import GrowwAPI

    totp = generate_totp(totp_secret)
    token = GrowwAPI.get_access_token(api_key=api_key, totp=totp)
    if not token:
        raise RuntimeError("Groww did not return access token")
    expires = datetime.now(timezone.utc) + timedelta(days=1)
    return {"access_token": token, "expires_at": expires}


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
