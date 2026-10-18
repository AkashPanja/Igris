"""Multi-provider LLM runtime: streaming + tool-calling with a normalized event stream.

Yields events: {"type":"text","text"} | {"type":"tool_calls","tool_calls":[{id,name,arguments}]}
| {"type":"done","usage"} | {"type":"error","message"}
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

TIMEOUT = httpx.Timeout(120.0, connect=10.0)
MAX_TOKENS = 2048
TEMPERATURE = 0.3

OPENAI_COMPAT = {"openai", "groq", "openrouter", "custom", "cloudflare"}
DEFAULT_BASE = {
    "openai": "https://api.openai.com/v1",
    "groq": "https://api.groq.com/openai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
}


def _base_url(provider: str, base_url: str) -> str:
    if base_url.strip():
        return base_url.strip().rstrip("/")
    return DEFAULT_BASE.get(provider, "https://api.openai.com/v1")


async def stream_chat(
    provider: str,
    api_key: str,
    model: str,
    base_url: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Dispatch to the right adapter based on provider."""
    if provider == "anthropic":
        async for ev in _anthropic_stream(api_key, model, messages, tools):
            yield ev
    elif provider == "gemini":
        async for ev in _gemini_stream(api_key, model, messages, tools):
            yield ev
    elif provider in OPENAI_COMPAT:
        async for ev in _openai_stream(provider, api_key, model, base_url, messages, tools):
            yield ev
    else:
        yield {"type": "error", "message": f"Unsupported provider: {provider}"}


# --------------------------------------------------------------------- openai


def _openai_tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    if not tools:
        return None
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("parameters", {"type": "object", "properties": {}}),
            },
        }
        for t in tools
    ]


def _openai_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in messages:
        if m["role"] == "tool":
            out.append(
                {
                    "role": "tool",
                    "tool_call_id": m.get("tool_call_id", ""),
                    "content": m.get("content", ""),
                }
            )
        elif m["role"] == "assistant" and m.get("tool_calls"):
            out.append(
                {
                    "role": "assistant",
                    "content": m.get("content") or None,
                    "tool_calls": [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {
                                "name": tc["name"],
                                "arguments": json.dumps(tc.get("arguments", {})),
                            },
                        }
                        for tc in m["tool_calls"]
                    ],
                }
            )
        else:
            out.append({"role": m["role"], "content": m.get("content", "")})
    return out


async def _openai_stream(
    provider: str, api_key: str, model: str, base_url: str,
    messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None,
) -> AsyncIterator[dict[str, Any]]:
    url = _base_url(provider, base_url) + "/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    if provider == "openrouter":
        headers["HTTP-Referer"] = "https://igris.local"
        headers["X-Title"] = "Igris"
    payload: dict[str, Any] = {
        "model": model,
        "messages": _openai_messages(messages),
        "max_tokens": MAX_TOKENS,
        "temperature": TEMPERATURE,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    tool_list = _openai_tools(tools)
    if tool_list:
        payload["tools"] = tool_list
        payload["tool_choice"] = "auto"

    acc: dict[int, dict[str, Any]] = {}
    usage: dict[str, Any] | None = None
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            async with client.stream("POST", url, headers=headers, json=payload) as resp:
                if resp.status_code >= 400:
                    body = (await resp.aread()).decode(errors="replace")
                    yield {"type": "error", "message": f"HTTP {resp.status_code}: {body[:400]}"}
                    return
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    if chunk.get("usage"):
                        usage = chunk["usage"]
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    if delta.get("content"):
                        yield {"type": "text", "text": delta["content"]}
                    for tc in delta.get("tool_calls") or []:
                        idx = tc.get("index", 0)
                        slot = acc.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                        if tc.get("id"):
                            slot["id"] = tc["id"]
                        fn = tc.get("function") or {}
                        if fn.get("name"):
                            slot["name"] = fn["name"]
                        if fn.get("arguments"):
                            slot["arguments"] += fn["arguments"]
    except httpx.HTTPError as exc:
        yield {"type": "error", "message": f"network: {exc}"}
        return

    if acc:
        calls = []
        for i in sorted(acc):
            slot = acc[i]
            try:
                args = json.loads(slot["arguments"] or "{}")
            except json.JSONDecodeError:
                args = {"_raw": slot["arguments"]}
            calls.append({"id": slot["id"] or f"call_{i}", "name": slot["name"], "arguments": args})
        yield {"type": "tool_calls", "tool_calls": calls}
    yield {"type": "done", "usage": usage}


# ------------------------------------------------------------------- anthropic


def _anthropic_tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    if not tools:
        return None
    return [
        {
            "name": t["name"],
            "description": t.get("description", ""),
            "input_schema": t.get("parameters", {"type": "object", "properties": {}}),
        }
        for t in tools
    ]


def _anthropic_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in messages:
        if m["role"] == "system":
            continue
        if m["role"] == "assistant" and m.get("tool_calls"):
            content: list[dict[str, Any]] = []
            if m.get("content"):
                content.append({"type": "text", "text": m["content"]})
            for tc in m["tool_calls"]:
                content.append(
                    {"type": "tool_use", "id": tc["id"], "name": tc["name"], "input": tc.get("arguments", {})}
                )
            out.append({"role": "assistant", "content": content})
        elif m["role"] == "tool":
            if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list) and out[-1]["content"] and out[-1]["content"][0].get("type") == "tool_result":
                out[-1]["content"].append(
                    {"type": "tool_result", "tool_use_id": m.get("tool_call_id", ""), "content": m.get("content", "")}
                )
            else:
                out.append(
                    {
                        "role": "user",
                        "content": [
                            {"type": "tool_result", "tool_use_id": m.get("tool_call_id", ""), "content": m.get("content", "")}
                        ],
                    }
                )
        else:
            out.append({"role": m["role"], "content": m.get("content", "")})
    return out


async def _anthropic_stream(
    api_key: str, model: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None,
) -> AsyncIterator[dict[str, Any]]:
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    system = "\n\n".join(m.get("content", "") for m in messages if m["role"] == "system")
    payload: dict[str, Any] = {
        "model": model,
        "max_tokens": MAX_TOKENS,
        "temperature": TEMPERATURE,
        "messages": _anthropic_messages(messages),
    }
    if system:
        payload["system"] = system
    tool_list = _anthropic_tools(tools)
    if tool_list:
        payload["tools"] = tool_list

    blocks: list[dict[str, Any]] = []  # accumulated content blocks
    usage: dict[str, Any] | None = None
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            async with client.stream("POST", url, headers=headers, json=payload) as resp:
                if resp.status_code >= 400:
                    body = (await resp.aread()).decode(errors="replace")
                    yield {"type": "error", "message": f"HTTP {resp.status_code}: {body[:400]}"}
                    return
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    try:
                        ev = json.loads(line[5:].strip())
                    except json.JSONDecodeError:
                        continue
                    etype = ev.get("type")
                    if etype == "content_block_start":
                        blocks.append(dict(ev.get("content_block") or {}))
                    elif etype == "content_block_delta":
                        delta = ev.get("delta") or {}
                        idx = ev.get("index", 0)
                        if idx >= len(blocks):
                            continue
                        if delta.get("type") == "text_delta" and delta.get("text"):
                            yield {"type": "text", "text": delta["text"]}
                            blocks[idx]["_text"] = blocks[idx].get("_text", "") + delta["text"]
                        elif delta.get("type") == "input_json_delta":
                            blocks[idx]["_json"] = blocks[idx].get("_json", "") + delta.get("partial_json", "")
                    elif etype == "message_delta":
                        usage = (ev.get("usage") or usage)
                    elif etype == "error":
                        yield {"type": "error", "message": (ev.get("error") or {}).get("message", "anthropic error")}
                        return
    except httpx.HTTPError as exc:
        yield {"type": "error", "message": f"network: {exc}"}
        return

    calls = []
    for b in blocks:
        if b.get("type") == "tool_use":
            raw = b.get("_json") or ""
            try:
                args = json.loads(raw or "{}")
            except json.JSONDecodeError:
                args = {"_raw": raw}
            calls.append({"id": b.get("id", ""), "name": b.get("name", ""), "arguments": args})
    if calls:
        yield {"type": "tool_calls", "tool_calls": calls}
    yield {"type": "done", "usage": usage}


# ---------------------------------------------------------------------- gemini


def _gemini_contents(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    contents: list[dict[str, Any]] = []
    for m in messages:
        if m["role"] == "system":
            continue
        if m["role"] == "assistant":
            parts: list[dict[str, Any]] = []
            if m.get("content"):
                parts.append({"text": m["content"]})
            for tc in m.get("tool_calls") or []:
                parts.append({"functionCall": {"name": tc["name"], "args": tc.get("arguments", {})}})
            if parts:
                contents.append({"role": "model", "parts": parts})
        elif m["role"] == "tool":
            resp: dict[str, Any]
            try:
                resp = {"result": json.loads(m.get("content", "{}"))}
            except json.JSONDecodeError:
                resp = {"result": m.get("content", "")}
            contents.append(
                {"role": "user", "parts": [{"functionResponse": {"name": m.get("name", "tool"), "response": resp}}]}
            )
        else:
            contents.append({"role": "user", "parts": [{"text": m.get("content", "")}]})
    return contents


async def _gemini_stream(
    api_key: str, model: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None,
) -> AsyncIterator[dict[str, Any]]:
    base = "https://generativelanguage.googleapis.com/v1beta"
    url = f"{base}/models/{model}:streamGenerateContent?alt=sse&key={api_key}"
    system = "\n\n".join(m.get("content", "") for m in messages if m["role"] == "system")
    payload: dict[str, Any] = {
        "contents": _gemini_contents(messages),
        "generationConfig": {"maxOutputTokens": MAX_TOKENS, "temperature": TEMPERATURE},
    }
    if system:
        payload["systemInstruction"] = {"parts": [{"text": system}]}
    if tools:
        payload["tools"] = [
            {
                "functionDeclarations": [
                    {
                        "name": t["name"],
                        "description": t.get("description", ""),
                        "parameters": t.get("parameters", {"type": "object", "properties": {}}),
                    }
                    for t in tools
                ]
            }
        ]

    calls: list[dict[str, Any]] = []
    usage: dict[str, Any] | None = None
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            async with client.stream("POST", url, json=payload) as resp:
                if resp.status_code >= 400:
                    body = (await resp.aread()).decode(errors="replace")
                    yield {"type": "error", "message": f"HTTP {resp.status_code}: {body[:400]}"}
                    return
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    try:
                        chunk = json.loads(line[5:].strip())
                    except json.JSONDecodeError:
                        continue
                    if chunk.get("usageMetadata"):
                        usage = chunk["usageMetadata"]
                    for cand in chunk.get("candidates") or []:
                        for part in ((cand.get("content") or {}).get("parts") or []):
                            if part.get("text"):
                                yield {"type": "text", "text": part["text"]}
                            fc = part.get("functionCall")
                            if fc:
                                calls.append(
                                    {
                                        "id": f"call_{len(calls)}",
                                        "name": fc.get("name", ""),
                                        "arguments": fc.get("args", {}),
                                    }
                                )
    except httpx.HTTPError as exc:
        yield {"type": "error", "message": f"network: {exc}"}
        return

    if calls:
        yield {"type": "tool_calls", "tool_calls": calls}
    yield {"type": "done", "usage": usage}
