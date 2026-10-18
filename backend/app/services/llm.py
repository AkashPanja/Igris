from __future__ import annotations

import time
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import LlmConnection
from app.utils.crypto import decrypt, encrypt

PROVIDERS: dict[str, dict] = {
    "openai": {
        "label": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "key_hint": "sk-…",
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-4.1", "gpt-4.1-mini", "o4-mini"],
        "docs": "https://platform.openai.com/api-keys",
    },
    "anthropic": {
        "label": "Anthropic (Claude)",
        "base_url": "https://api.anthropic.com",
        "key_hint": "sk-ant-…",
        "models": [
            "claude-sonnet-4-20250514",
            "claude-opus-4-20250514",
            "claude-3-5-haiku-20241022",
        ],
        "docs": "https://console.anthropic.com/settings/keys",
    },
    "gemini": {
        "label": "Google Gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "key_hint": "AIza…",
        "models": ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.0-flash"],
        "docs": "https://aistudio.google.com/apikey",
    },
    "groq": {
        "label": "Groq",
        "base_url": "https://api.groq.com/openai/v1",
        "key_hint": "gsk_…",
        "models": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"],
        "docs": "https://console.groq.com/keys",
    },
    "openrouter": {
        "label": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "key_hint": "sk-or-…",
        "models": ["openai/gpt-4o", "anthropic/claude-sonnet-4", "meta-llama/llama-3.3-70b-instruct"],
        "docs": "https://openrouter.ai/settings/keys",
    },
    "cloudflare": {
        "label": "Cloudflare Workers AI",
        "base_url": "",
        "key_hint": "CF account token",
        "models": [],
        "docs": "https://developers.cloudflare.com/workers-ai/platform/openai-compatibility/",
    },
    "custom": {
        "label": "OpenAI-compatible (custom)",
        "base_url": "",
        "key_hint": "any key",
        "models": [],
        "docs": "",
    },
}

TIMEOUT = httpx.Timeout(30.0)


def mask_key(value: str) -> str:
    v = (value or "").strip()
    if not v:
        return ""
    if len(v) <= 12:
        return "••••••"
    return f"{v[:6]}…{v[-4:]}"


def load_key(row: LlmConnection) -> str:
    if not row.api_key_encrypted:
        return ""
    try:
        return decrypt(row.api_key_encrypted)
    except ValueError:
        return ""


def save_key(row: LlmConnection, key: str) -> None:
    row.api_key_encrypted = encrypt(key) if key else ""


def public_view(row: LlmConnection) -> dict:
    meta = PROVIDERS.get(row.provider, {})
    return {
        "id": row.id,
        "provider": row.provider,
        "provider_label": meta.get("label", row.provider),
        "label": row.label,
        "api_key_masked": mask_key(load_key(row)),
        "base_url": row.base_url,
        "model": row.model,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


async def list_connections(session: AsyncSession, user_id: int) -> list[LlmConnection]:
    result = await session.execute(
        select(LlmConnection)
        .where(LlmConnection.user_id == user_id)
        .order_by(LlmConnection.created_at)
    )
    return list(result.scalars())


async def get_connection(session: AsyncSession, user_id: int, conn_id: str) -> LlmConnection | None:
    row = await session.get(LlmConnection, conn_id)
    if not row or row.user_id != user_id:
        return None
    return row


def new_id() -> str:
    import secrets

    return secrets.token_urlsafe(18)


async def _openai_chat(base_url: str, api_key: str, model: str) -> dict:
    url = base_url.rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
    }
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.post(url, headers=headers, json=payload)
        data = r.json()
        if r.status_code >= 400:
            msg = (data.get("error") or {}).get("message") or data.get("message") or f"HTTP {r.status_code}"
            raise RuntimeError(msg)
        return data


async def test_connection(row: LlmConnection, api_key: str) -> tuple[bool, str]:
    """Tiny real call to the provider; success proves key + model work."""
    if not api_key:
        return False, "API key missing"
    provider, model = row.provider, (row.model or "").strip()
    if not model and provider != "openrouter":
        return False, "No model selected"
    start = time.monotonic()
    try:
        if provider == "anthropic":
            url = (PROVIDERS["anthropic"]["base_url"]) + "/v1/messages"
            headers = {
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            }
            payload = {"model": model, "max_tokens": 1, "messages": [{"role": "user", "content": "ping"}]}
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                r = await client.post(url, headers=headers, json=payload)
                data = r.json()
                if r.status_code >= 400:
                    msg = (data.get("error") or {}).get("message") or f"HTTP {r.status_code}"
                    raise RuntimeError(msg)
        elif provider == "gemini":
            url = (PROVIDERS["gemini"]["base_url"]) + f"/models/{model}:generateContent?key={api_key}"
            payload = {"contents": [{"parts": [{"text": "ping"}]}]}
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                r = await client.post(url, json=payload)
                data = r.json()
                if r.status_code >= 400:
                    msg = (data.get("error") or {}).get("message") or f"HTTP {r.status_code}"
                    raise RuntimeError(msg)
        elif provider in ("custom", "cloudflare"):
            if not row.base_url.strip():
                return False, f"Base URL required for {provider} provider"
            await _openai_chat(row.base_url, api_key, model)
        else:  # openai | groq | openrouter — OpenAI-compatible chat
            base = PROVIDERS[provider]["base_url"]
            await _openai_chat(base, api_key, model or "default")
        ms = int((time.monotonic() - start) * 1000)
        return True, f"OK · {model or 'default'} · {ms}ms"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
