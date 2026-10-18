from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.routers.connections import current_user
from app.schemas import Message
from app.services import llm as svc

router = APIRouter()


class CreateLlm(BaseModel):
    provider: str = Field(pattern="^(openai|anthropic|gemini|groq|openrouter|cloudflare|custom)$")
    label: str = ""
    api_key: str = Field(min_length=1)
    base_url: str = ""
    model: str = ""


class PatchLlm(BaseModel):
    label: str | None = None
    model: str | None = None
    api_key: str | None = None
    base_url: str | None = None


@router.get("/config")
async def llm_config(user=Depends(current_user)) -> dict:
    return {
        "providers": [
            {
                "id": pid,
                "label": meta["label"],
                "key_hint": meta["key_hint"],
                "models": meta["models"],
                "base_url_required": pid in ("custom", "cloudflare"),
                "docs": meta["docs"],
            }
            for pid, meta in svc.PROVIDERS.items()
        ]
    }


@router.get("")
async def list_llm(
    session: AsyncSession = Depends(get_session), user=Depends(current_user)
) -> list[dict]:
    rows = await svc.list_connections(session, user[0].id)
    return [svc.public_view(r) for r in rows]


@router.post("")
async def create_llm(
    body: CreateLlm,
    session: AsyncSession = Depends(get_session),
    user=Depends(current_user),
) -> dict:
    meta = svc.PROVIDERS.get(body.provider)
    if not meta:
        raise HTTPException(status_code=422, detail="Unknown provider")
    if body.provider in ("custom", "cloudflare") and not body.base_url.strip():
        raise HTTPException(status_code=422, detail=f"Base URL is required for {body.provider} provider")
    row = svc.LlmConnection(
        id=svc.new_id(),
        user_id=user[0].id,
        provider=body.provider,
        label=body.label.strip() or meta["label"],
        base_url=body.base_url.strip(),
        model=body.model.strip(),
    )
    svc.save_key(row, body.api_key.strip())
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return svc.public_view(row)


@router.patch("/{conn_id}", response_model=Message)
async def patch_llm(
    conn_id: str,
    body: PatchLlm,
    session: AsyncSession = Depends(get_session),
    user=Depends(current_user),
) -> Message:
    row = await svc.get_connection(session, user[0].id, conn_id)
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    if body.label is not None:
        row.label = body.label.strip() or row.label
    if body.model is not None:
        row.model = body.model.strip()
    if body.base_url is not None:
        row.base_url = body.base_url.strip()
    if body.api_key is not None and body.api_key.strip():
        svc.save_key(row, body.api_key.strip())
    await session.commit()
    return Message(detail="updated")


@router.delete("/{conn_id}", response_model=Message)
async def delete_llm(
    conn_id: str,
    session: AsyncSession = Depends(get_session),
    user=Depends(current_user),
) -> Message:
    row = await svc.get_connection(session, user[0].id, conn_id)
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    await session.delete(row)
    await session.commit()
    return Message(detail="deleted")


@router.post("/{conn_id}/test")
async def test_llm(
    conn_id: str,
    session: AsyncSession = Depends(get_session),
    user=Depends(current_user),
) -> dict:
    row = await svc.get_connection(session, user[0].id, conn_id)
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    key = svc.load_key(row)
    ok, msg = await svc.test_connection(row, key)
    return {"success": ok, "message": msg}
