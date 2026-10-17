from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_session
from app.models import Connection
from app.schemas import Message
from app.services import auth as auth_service
from app.services import connections as svc
from app.services.brokers import fyers as fyers_broker
from app.services.brokers import groww as groww_broker

router = APIRouter()


async def current_user(
    request: Request, session: AsyncSession = Depends(get_session)
) -> tuple:
    sid = request.cookies.get(settings.session_cookie_name, "")
    result = await auth_service.get_session_user(session, sid)
    if not result:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return result[0], result[1]


class CreateConnection(BaseModel):
    provider: str = Field(pattern="^(fyers|groww)$")
    label: str = ""
    app_id: str = ""            # fyers app id | groww api key
    app_secret: str = ""        # fyers secret | groww totp secret


class PatchConnection(BaseModel):
    label: str | None = None
    reauth_time: str | None = Field(default=None, pattern="^([01][0-9]|2[0-3]):[0-5][0-9]$")


class ManualAuth(BaseModel):
    code: str = Field(min_length=1)


@router.get("/config")
async def connection_config(user=Depends(current_user)) -> dict:
    return {
        "public_base_url": settings.public_base_url,
        "manual_flow": fyers_broker.is_manual_flow(),
        "redirect_uri": fyers_broker.redirect_uri(),
        "help": svc.PROVIDER_HELP,
        "tools": svc.TOOLS,
    }


@router.get("")
async def list_connections(
    session: AsyncSession = Depends(get_session), user=Depends(current_user)
) -> list[dict]:
    user_obj, _ = user if isinstance(user, tuple) else (user, None)
    conns = await svc.list_connections(session, user_obj.id)
    return [svc.public_view(c, user_obj) for c in conns]


@router.post("", response_model=Message)
async def create_connection(
    body: CreateConnection,
    session: AsyncSession = Depends(get_session),
    user=Depends(current_user),
) -> Message:
    user_obj = user[0]
    if body.provider not in svc.PROVIDERS:
        raise HTTPException(status_code=422, detail="Unknown provider")
    if not body.app_id.strip():
        raise HTTPException(status_code=422, detail="App ID / API key is required")

    creds: dict = {}
    if body.provider == "fyers":
        if not body.app_secret.strip():
            raise HTTPException(status_code=422, detail="App secret is required")
        creds["app_secret"] = body.app_secret.strip()
    else:
        if not body.app_secret.strip():
            raise HTTPException(status_code=422, detail="TOTP secret is required")
        creds["totp_secret"] = body.app_secret.strip()

    await svc.create_connection(
        session,
        user_obj.id,
        body.provider,
        body.label.strip(),
        body.app_id.strip(),
        creds,
    )
    return Message(detail="created")


@router.patch("/{conn_id}", response_model=Message)
async def patch_connection(
    conn_id: str,
    body: PatchConnection,
    session: AsyncSession = Depends(get_session),
    user=Depends(current_user),
) -> Message:
    user_obj = user[0]
    conn = await svc.get_connection(session, user_obj.id, conn_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Not found")
    if body.label is not None:
        conn.label = body.label.strip() or conn.label
    if body.reauth_time is not None:
        conn.reauth_time = body.reauth_time
    await session.commit()
    return Message(detail="updated")


@router.delete("/{conn_id}", response_model=Message)
async def delete_connection(
    conn_id: str,
    session: AsyncSession = Depends(get_session),
    user=Depends(current_user),
) -> Message:
    user_obj = user[0]
    conn = await svc.get_connection(session, user_obj.id, conn_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Not found")
    await svc.delete_connection(session, conn)
    return Message(detail="deleted")


@router.post("/{conn_id}/auth-url")
async def auth_url(
    conn_id: str,
    session: AsyncSession = Depends(get_session),
    user=Depends(current_user),
) -> dict:
    user_obj = user[0]
    conn = await svc.get_connection(session, user_obj.id, conn_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Not found")
    if conn.provider != "fyers":
        raise HTTPException(status_code=400, detail="Only Fyers uses OAuth URL")
    url = fyers_broker.build_auth_url(conn.id, conn.app_id)
    return {"url": url, "manual": fyers_broker.is_manual_flow()}


@router.post("/{conn_id}/complete-auth", response_model=Message)
async def complete_auth(
    conn_id: str,
    body: ManualAuth,
    session: AsyncSession = Depends(get_session),
    user=Depends(current_user),
) -> Message:
    user_obj = user[0]
    conn = await svc.get_connection(session, user_obj.id, conn_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Not found")
    creds = svc.load_credentials(conn)
    try:
        result = await fyers_broker.exchange_code(
            conn.app_id, creds.get("app_secret", ""), body.code.strip()
        )
    except Exception as exc:  # noqa: BLE001
        conn.status = "error"
        conn.last_error = str(exc)
        await session.commit()
        raise HTTPException(status_code=400, detail=str(exc))
    creds["access_token"] = result["access_token"]
    svc.save_credentials(conn, creds)
    conn.status = "connected"
    conn.expires_at = result["expires_at"]
    conn.last_error = ""
    conn.last_reauth_at = datetime.now(timezone.utc)
    await session.commit()
    return Message(detail="connected")


@router.get("/fyers/callback")
async def fyers_callback(
    request: Request,
    code: str = "",
    state: str = "",
    error: str = "",
    session: AsyncSession = Depends(get_session),
) -> Message:
    # OAuth lands here unauthenticated (cookie IS sent — same site) but we
    # resolve the connection purely via state to be safe.
    conn = await session.get(Connection, state) if state else None
    if error or not code or not conn:
        return Message(detail="oauth_failed")
    creds = svc.load_credentials(conn)
    try:
        result = await fyers_broker.exchange_code(
            conn.app_id, creds.get("app_secret", ""), code
        )
    except Exception:  # noqa: BLE001
        conn.status = "error"
        conn.last_error = "Token exchange failed"
        await session.commit()
        return Message(detail="exchange_failed")
    creds["access_token"] = result["access_token"]
    svc.save_credentials(conn, creds)
    conn.status = "connected"
    conn.expires_at = result["expires_at"]
    conn.last_error = ""
    conn.last_reauth_at = datetime.now(timezone.utc)
    await session.commit()
    # Redirect browser to frontend connections page
    from fastapi.responses import RedirectResponse

    return RedirectResponse(url="/connections?fyers=ok", status_code=302)


@router.post("/{conn_id}/connect-groww", response_model=Message)
async def connect_groww(
    conn_id: str,
    session: AsyncSession = Depends(get_session),
    user=Depends(current_user),
) -> Message:
    user_obj = user[0]
    conn = await svc.get_connection(session, user_obj.id, conn_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Not found")
    if conn.provider != "groww":
        raise HTTPException(status_code=400, detail="Not a Groww connection")
    creds = svc.load_credentials(conn)
    try:
        result = await groww_broker.connect(conn.app_id, creds.get("totp_secret", ""))
    except Exception as exc:  # noqa: BLE001
        conn.status = "error"
        conn.last_error = str(exc)
        await session.commit()
        raise HTTPException(status_code=400, detail=str(exc))
    creds["access_token"] = result["access_token"]
    svc.save_credentials(conn, creds)
    conn.status = "connected"
    conn.expires_at = result["expires_at"]
    conn.last_error = ""
    conn.last_reauth_at = datetime.now(timezone.utc)
    await session.commit()
    return Message(detail="connected")


@router.post("/{conn_id}/test")
async def test_connection(
    conn_id: str,
    session: AsyncSession = Depends(get_session),
    user=Depends(current_user),
) -> dict:
    user_obj = user[0]
    conn = await svc.get_connection(session, user_obj.id, conn_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Not found")
    creds = svc.load_credentials(conn)
    token = creds.get("access_token", "")
    if conn.provider == "fyers":
        ok, msg = await fyers_broker.test_connection(conn.app_id, token)
    else:
        ok, msg = await groww_broker.test_connection(token)
    return {"success": ok, "message": msg}
