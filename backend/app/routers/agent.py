from __future__ import annotations

import json
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import (
    AgentSettings,
    AuditLog,
    ConfirmToken,
    Conversation,
    CronJob,
    Lesson,
    MemoryEdge,
    Message,
    Notification,
    Proposal,
    ResearchNote,
    Signal,
    User,
    WatchlistItem,
    utcnow,
)
from app.routers.connections import current_user
from app.schemas import Message as MessageSchema
from app.services.agent import trading
from app.services.agent.chat import run_chat
from app.services.agent.tools import (
    execute_tool,
    proposal_view,
    run_confirm_token,
    tool_specs_for_llm,
)
from app.services.llm import list_connections as list_llm_connections
from app.services.llm import load_key

router = APIRouter()


# ------------------------------------------------------------------ chat


class ChatIn(BaseModel):
    conversation_id: str | None = None
    content: str = Field(min_length=1, max_length=8000)


class ConversationIn(BaseModel):
    title: str = ""


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, default=str)}\n\n"


async def _llm_for_user(session: AsyncSession, user_id: int) -> tuple:
    settings = await session.get(AgentSettings, user_id)
    rows = await list_llm_connections(session, user_id)
    if not rows:
        raise HTTPException(status_code=400, detail="Add an LLM connection first (LLM tab).")
    row = None
    if settings and settings.llm_connection_id:
        row = next((r for r in rows if r.id == settings.llm_connection_id), None)
    row = row or rows[0]
    key = load_key(row)
    if not key:
        raise HTTPException(status_code=400, detail="LLM connection has no usable API key.")
    return row.provider, key, row.model, row.base_url


@router.get("/conversations")
async def list_conversations(session: AsyncSession = Depends(get_session), user=Depends(current_user)):
    rows = (await session.execute(
        select(Conversation).where(Conversation.user_id == user[0].id)
        .order_by(Conversation.updated_at.desc()).limit(100)
    )).scalars()
    return [{"id": r.id, "title": r.title,
             "created_at": r.created_at.isoformat(), "updated_at": r.updated_at.isoformat()} for r in rows]


@router.post("/conversations")
async def create_conversation(
    body: ConversationIn, session: AsyncSession = Depends(get_session), user=Depends(current_user)
):
    import secrets

    conv = Conversation(id=secrets.token_urlsafe(12), user_id=user[0].id,
                        title=body.title.strip() or "New chat")
    session.add(conv)
    await session.commit()
    return {"id": conv.id, "title": conv.title}


@router.delete("/conversations/{conv_id}", response_model=MessageSchema)
async def delete_conversation(
    conv_id: str, session: AsyncSession = Depends(get_session), user=Depends(current_user)
):
    conv = await session.get(Conversation, conv_id)
    if not conv or conv.user_id != user[0].id:
        raise HTTPException(status_code=404, detail="Not found")
    msgs = (await session.execute(select(Message).where(Message.conversation_id == conv_id))).scalars()
    for m in msgs:
        await session.delete(m)
    await session.delete(conv)
    await session.commit()
    return MessageSchema(detail="deleted")


@router.get("/conversations/{conv_id}/messages")
async def get_messages(
    conv_id: str, session: AsyncSession = Depends(get_session), user=Depends(current_user)
):
    conv = await session.get(Conversation, conv_id)
    if not conv or conv.user_id != user[0].id:
        raise HTTPException(status_code=404, detail="Not found")
    rows = (await session.execute(
        select(Message).where(Message.conversation_id == conv_id).order_by(Message.id)
    )).scalars()
    return [{"id": r.id, "role": r.role, "content": r.content,
             "tool_json": json.loads(r.tool_json or "[]"),
             "created_at": r.created_at.isoformat()} for r in rows]


@router.post("/chat")
async def chat(body: ChatIn, session: AsyncSession = Depends(get_session), user=Depends(current_user)):
    provider, key, model, base_url = await _llm_for_user(session, user[0].id)
    if body.conversation_id:
        conv = await session.get(Conversation, body.conversation_id)
        if not conv or conv.user_id != user[0].id:
            raise HTTPException(status_code=404, detail="Conversation not found")
    else:
        import secrets

        conv = Conversation(id=secrets.token_urlsafe(12), user_id=user[0].id, title="New chat")
        session.add(conv)
        await session.commit()

    async def gen():
        yield _sse({"type": "meta", "conversation_id": conv.id, "model": model, "provider": provider})
        try:
            async for ev in run_chat(session, user[0], conv, body.content, provider, key, model, base_url):
                yield _sse(ev)
        except Exception as exc:  # noqa: BLE001
            yield _sse({"type": "error", "message": f"{type(exc).__name__}: {exc}"})

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


class ConfirmIn(BaseModel):
    token: str


@router.post("/confirm")
async def confirm_tool(
    body: ConfirmIn, session: AsyncSession = Depends(get_session), user=Depends(current_user)
):
    return await run_confirm_token(session, user[0], body.token)


@router.get("/tools")
async def list_tools(user=Depends(current_user)):
    return {"tools": tool_specs_for_llm()}


# --------------------------------------------------------------- rules/mode


@router.get("/rules")
async def get_rules(session: AsyncSession = Depends(get_session), user=Depends(current_user)):
    r = await trading.get_rules(session, user[0].id)
    return {
        "capital": r.capital,
        "risk_per_trade_pct": r.risk_per_trade_pct,
        "max_open_positions": r.max_open_positions,
        "daily_loss_limit_pct": r.daily_loss_limit_pct,
        "max_daily_trades": r.max_daily_trades,
        "mode": r.mode,
        "autonomy": r.autonomy,
        "instruments_allowed": json.loads(r.instruments_allowed or "[]"),
        "strategy_id": r.strategy_id,
        "kill_switch": r.kill_switch,
        "notify_on_long": r.notify_on_long,
        "hard_caps": trading.HARD_CAPS,
    }


class RulesIn(BaseModel):
    capital: float | None = None
    risk_per_trade_pct: float | None = None
    max_open_positions: int | None = None
    daily_loss_limit_pct: float | None = None
    max_daily_trades: int | None = None
    instruments_allowed: list[str] | None = None
    strategy_id: str | None = None
    notify_on_long: bool | None = None


@router.patch("/rules", response_model=MessageSchema)
async def patch_rules(
    body: RulesIn, session: AsyncSession = Depends(get_session), user=Depends(current_user)
):
    rule = await trading.get_rules(session, user[0].id)
    data = body.model_dump(exclude_none=True)
    if "instruments_allowed" in data:
        data["instruments_allowed"] = json.dumps(
            [i for i in data["instruments_allowed"] if i in trading.INSTRUMENTS]
        )
    if "strategy_id" in data:
        data["strategy_id"] = (data["strategy_id"] or "")[:32]
    clamped, warnings = trading.clamp_rules(data)
    for k, v in clamped.items():
        setattr(rule, k, v)
    rule.updated_at = utcnow()
    await trading.audit(session, user[0].id, "user", "rules_updated", json.dumps(clamped))
    await session.commit()
    return MessageSchema(detail="updated" + (f" (clamped: {warnings})" if warnings else ""))


class ModeIn(BaseModel):
    mode: str = Field(pattern="^(paper|live)$")
    autonomy: str | None = Field(default=None, pattern="^(paper|live_approve|live_auto)$")
    confirm: str = ""


@router.post("/mode", response_model=MessageSchema)
async def set_mode(
    body: ModeIn, session: AsyncSession = Depends(get_session), user=Depends(current_user)
):
    """Website-only mode switch. Live requires typing LIVE (paper §6.3)."""
    rule = await trading.get_rules(session, user[0].id)
    if rule.kill_switch and body.mode == "live":
        raise HTTPException(status_code=409, detail="Kill switch engaged — clear it on the website first.")
    if body.mode == "live" and body.confirm.strip().upper() != "LIVE":
        raise HTTPException(status_code=422, detail='Type "LIVE" to enable real-money trading.')
    if rule.mode == "live" and body.mode == "paper":
        rule.autonomy = "paper"
    rule.mode = body.mode
    if body.autonomy:
        rule.autonomy = body.autonomy
    elif body.mode == "live" and rule.autonomy == "paper":
        rule.autonomy = "live_approve"
    elif body.mode == "paper":
        rule.autonomy = "paper"
    rule.updated_at = utcnow()
    await trading.audit(session, user[0].id, "user", "mode_changed", f"mode={rule.mode} autonomy={rule.autonomy}")
    await trading.notify(session, user[0], "system",
                         f"Trading mode: {rule.mode.upper()}",
                         f"Autonomy: {rule.autonomy}", email=(body.mode == "live"))
    await session.commit()
    return MessageSchema(detail=f"mode={rule.mode} autonomy={rule.autonomy}")


@router.post("/kill", response_model=MessageSchema)
async def kill_switch(session: AsyncSession = Depends(get_session), user=Depends(current_user)):
    rule = await trading.get_rules(session, user[0].id)
    n = await trading.kill_switch_halt(session, user[0], rule)
    await session.commit()
    return MessageSchema(detail=f"halted {n} trades; mode forced to paper")


@router.post("/kill/reset", response_model=MessageSchema)
async def kill_reset(session: AsyncSession = Depends(get_session), user=Depends(current_user)):
    rule = await trading.get_rules(session, user[0].id)
    rule.kill_switch = False
    await trading.audit(session, user[0].id, "user", "kill_switch_reset", "")
    await session.commit()
    return MessageSchema(detail="kill switch cleared (mode remains paper)")


@router.get("/status")
async def status(session: AsyncSession = Depends(get_session), user=Depends(current_user)):
    from app.services.agent.tools import h_system_status

    return await h_system_status(session, user[0], {})


# ---------------------------------------------------------------- memory


@router.get("/memory/graph")
async def memory_graph(session: AsyncSession = Depends(get_session), user=Depends(current_user)):
    notes = list((await session.execute(
        select(ResearchNote).where(ResearchNote.user_id == user[0].id)
        .order_by(ResearchNote.created_at.desc()).limit(200)
    )).scalars())
    edges = list((await session.execute(
        select(MemoryEdge).where(MemoryEdge.user_id == user[0].id).limit(500)
    )).scalars())
    nodes = [
        {"id": n.id, "kind": "note", "label": n.title[:60], "pinned": n.pinned,
         "entities": json.loads(n.entities or "[]")}
        for n in notes
    ]
    seen_entities = set()
    for e in edges:
        if e.from_kind == "entity":
            seen_entities.add(e.from_id)
        if e.to_kind == "entity":
            seen_entities.add(e.to_id)
    for n in notes:
        for ent in json.loads(n.entities or "[]"):
            seen_entities.add(ent)
    nodes += [{"id": ent, "kind": "entity", "label": ent, "pinned": False, "entities": []}
              for ent in sorted(seen_entities)]
    return {
        "nodes": nodes,
        "edges": [{"from": f"{e.from_kind}:{e.from_id}", "to": f"{e.to_kind}:{e.to_id}", "rel": e.rel}
                  for e in edges] + [
            {"from": f"note:{n.id}", "to": f"entity:{ent}", "rel": "mentions"}
            for n in notes for ent in json.loads(n.entities or "[]")
        ],
    }


@router.get("/memory/notes")
async def list_notes(session: AsyncSession = Depends(get_session), user=Depends(current_user)):
    rows = (await session.execute(
        select(ResearchNote).where(ResearchNote.user_id == user[0].id)
        .order_by(ResearchNote.created_at.desc()).limit(200)
    )).scalars()
    return [{"id": r.id, "title": r.title, "body": r.body, "sentiment": r.sentiment,
             "entities": json.loads(r.entities or "[]"), "sources": json.loads(r.sources or "[]"),
             "pinned": r.pinned, "created_by": r.created_by,
             "created_at": r.created_at.isoformat()} for r in rows]


class NoteIn(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    body: str = ""
    entities: list[str] = []
    sentiment: float | None = None
    sources: list[str] = []
    pinned: bool | None = None


@router.post("/memory/notes")
async def create_note(
    body: NoteIn, session: AsyncSession = Depends(get_session), user=Depends(current_user)
):
    import uuid as _uuid

    note = ResearchNote(
        id=_uuid.uuid4().hex[:16], user_id=user[0].id, title=body.title,
        body=body.body[:8000], sentiment=body.sentiment,
        entities=json.dumps([e.upper() for e in body.entities]),
        sources=json.dumps(body.sources), created_by="user", pinned=body.pinned or False,
    )
    session.add(note)
    for e in body.entities:
        session.add(MemoryEdge(user_id=user[0].id, from_kind="note", from_id=note.id,
                               to_kind="entity", to_id=e.upper(), rel="mentions"))
    await trading.audit(session, user[0].id, "user", "note_written", body.title[:100])
    await session.commit()
    return {"id": note.id, "status": "saved"}


@router.patch("/memory/notes/{note_id}", response_model=MessageSchema)
async def patch_note(
    note_id: str, body: NoteIn, session: AsyncSession = Depends(get_session), user=Depends(current_user)
):
    note = await session.get(ResearchNote, note_id)
    if not note or note.user_id != user[0].id:
        raise HTTPException(status_code=404, detail="Not found")
    note.title = body.title
    note.body = body.body[:8000]
    note.sentiment = body.sentiment
    note.entities = json.dumps([e.upper() for e in body.entities])
    note.sources = json.dumps(body.sources)
    if body.pinned is not None:
        note.pinned = body.pinned
    await session.commit()
    return MessageSchema(detail="updated")


@router.delete("/memory/notes/{note_id}", response_model=MessageSchema)
async def delete_note(
    note_id: str, session: AsyncSession = Depends(get_session), user=Depends(current_user)
):
    note = await session.get(ResearchNote, note_id)
    if not note or note.user_id != user[0].id:
        raise HTTPException(status_code=404, detail="Not found")
    edges = (await session.execute(
        select(MemoryEdge).where(MemoryEdge.user_id == user[0].id,
                                 MemoryEdge.from_kind == "note", MemoryEdge.from_id == note_id)
    )).scalars()
    for e in edges:
        await session.delete(e)
    await session.delete(note)
    await session.commit()
    return MessageSchema(detail="deleted")


@router.get("/memory/watchlist")
async def list_watchlist(session: AsyncSession = Depends(get_session), user=Depends(current_user)):
    rows = (await session.execute(
        select(WatchlistItem).where(WatchlistItem.user_id == user[0].id).order_by(WatchlistItem.created_at.desc())
    )).scalars()
    return [{"id": r.id, "symbol": r.symbol, "notes": r.notes, "source": r.source} for r in rows]


class WatchIn(BaseModel):
    symbol: str = Field(min_length=1, max_length=64)
    notes: str = ""


@router.post("/memory/watchlist")
async def add_watch(
    body: WatchIn, session: AsyncSession = Depends(get_session), user=Depends(current_user)
):
    item = WatchlistItem(user_id=user[0].id, symbol=body.symbol.strip().upper(), notes=body.notes[:1000])
    session.add(item)
    await session.commit()
    return {"id": item.id, "status": "added"}


@router.delete("/memory/watchlist/{item_id}", response_model=MessageSchema)
async def del_watch(
    item_id: int, session: AsyncSession = Depends(get_session), user=Depends(current_user)
):
    item = await session.get(WatchlistItem, item_id)
    if not item or item.user_id != user[0].id:
        raise HTTPException(status_code=404, detail="Not found")
    await session.delete(item)
    await session.commit()
    return MessageSchema(detail="deleted")


@router.get("/memory/signals")
async def list_signals(session: AsyncSession = Depends(get_session), user=Depends(current_user)):
    rows = (await session.execute(
        select(Signal).where(Signal.user_id == user[0].id).order_by(Signal.created_at.desc()).limit(200)
    )).scalars()
    return [{"id": r.id, "symbol": r.symbol, "direction": r.direction, "catalyst": r.catalyst,
             "score": r.score, "source": r.source, "created_by": r.created_by} for r in rows]


@router.get("/proposals")
async def list_proposals(session: AsyncSession = Depends(get_session), user=Depends(current_user)):
    rows = (await session.execute(
        select(Proposal).where(Proposal.user_id == user[0].id).order_by(Proposal.created_at.desc()).limit(100)
    )).scalars()
    return [proposal_view(r) for r in rows]


@router.get("/trades")
async def list_trades(session: AsyncSession = Depends(get_session), user=Depends(current_user)):
    rows = (await session.execute(
        select(trading.Trade).where(trading.Trade.user_id == user[0].id)
        .order_by(trading.Trade.opened_at.desc()).limit(200)
    )).scalars()
    return [trading.trade_view(r) for r in rows]


@router.post("/trades/{trade_id}/approve", response_model=MessageSchema)
async def approve_trade(
    trade_id: str, session: AsyncSession = Depends(get_session), user=Depends(current_user)
):
    t = await session.get(trading.Trade, trade_id)
    if not t or t.user_id != user[0].id:
        raise HTTPException(status_code=404, detail="Not found")
    rule = await trading.get_rules(session, user[0].id)
    ok, msg = await trading.approve_trade(session, t, rule)
    await session.commit()
    if not ok:
        raise HTTPException(status_code=409, detail=msg)
    return MessageSchema(detail=f"order placed: {msg}")


@router.post("/trades/{trade_id}/close", response_model=MessageSchema)
async def close_trade(
    trade_id: str, session: AsyncSession = Depends(get_session), user=Depends(current_user)
):
    t = await session.get(trading.Trade, trade_id)
    if not t or t.user_id != user[0].id:
        raise HTTPException(status_code=404, detail="Not found")
    if t.status != "open":
        raise HTTPException(status_code=409, detail=f"Not open ({t.status})")
    px, _ = await trading.get_quote(session, user[0].id, t.symbol)
    await trading.close_trade(session, t, px if px else t.entry_px, "manual")
    await session.commit()
    return MessageSchema(detail="closed")


@router.get("/lessons")
async def list_lessons(session: AsyncSession = Depends(get_session), user=Depends(current_user)):
    rows = (await session.execute(
        select(Lesson).where(Lesson.user_id == user[0].id).order_by(Lesson.created_at.desc()).limit(100)
    )).scalars()
    return [{"id": r.id, "body": r.body, "metric": r.metric,
             "created_at": r.created_at.isoformat()} for r in rows]


@router.get("/audit")
async def list_audit(session: AsyncSession = Depends(get_session), user=Depends(current_user)):
    rows = (await session.execute(
        select(AuditLog).where(AuditLog.user_id == user[0].id).order_by(AuditLog.created_at.desc()).limit(200)
    )).scalars()
    return [{"id": r.id, "actor": r.actor, "action": r.action, "detail": r.detail[:500],
             "created_at": r.created_at.isoformat()} for r in rows]


# ------------------------------------------------------------ notifications


@router.get("/notifications")
async def list_notifications(session: AsyncSession = Depends(get_session), user=Depends(current_user)):
    rows = (await session.execute(
        select(Notification).where(Notification.user_id == user[0].id)
        .order_by(Notification.created_at.desc()).limit(100)
    )).scalars()
    return [{"id": r.id, "kind": r.kind, "title": r.title, "body": r.body, "read": r.read,
             "created_at": r.created_at.isoformat()} for r in rows]


@router.post("/notifications/read", response_model=MessageSchema)
async def mark_read(session: AsyncSession = Depends(get_session), user=Depends(current_user)):
    rows = (await session.execute(
        select(Notification).where(Notification.user_id == user[0].id, Notification.read == False)  # noqa: E712
    )).scalars()
    for r in rows:
        r.read = True
    await session.commit()
    return MessageSchema(detail=f"marked {len(rows)} read")


# ------------------------------------------------------------------- jobs


@router.get("/jobs")
async def list_jobs(session: AsyncSession = Depends(get_session), user=Depends(current_user)):
    rows = (await session.execute(
        select(CronJob).where(CronJob.user_id == user[0].id).order_by(CronJob.created_at.desc())
    )).scalars()
    return [{"id": r.id, "name": r.name, "tool_name": r.tool_name, "args": json.loads(r.args or "{}"),
             "interval_minutes": r.interval_minutes, "market_hours_only": r.market_hours_only,
             "enabled": r.enabled, "last_run_at": r.last_run_at.isoformat() if r.last_run_at else None,
             "last_result": r.last_result[:300]} for r in rows]


class JobIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    tool_name: str = Field(min_length=1, max_length=64)
    args: dict = {}
    interval_minutes: int = Field(default=60, ge=5, le=1440)
    market_hours_only: bool = True


@router.post("/jobs")
async def create_job(
    body: JobIn, session: AsyncSession = Depends(get_session), user=Depends(current_user)
):
    import uuid as _uuid

    if body.tool_name not in ("get_system_status", "research_symbol", "get_quote", "read_memory", "add_signal"):
        raise HTTPException(status_code=422, detail="tool not allowed in jobs")
    job = CronJob(
        id=_uuid.uuid4().hex[:12], user_id=user[0].id, name=body.name,
        tool_name=body.tool_name, args=json.dumps(body.args),
        interval_minutes=body.interval_minutes, market_hours_only=body.market_hours_only,
    )
    session.add(job)
    await trading.audit(session, user[0].id, "user", "job_scheduled", f"{job.name} → {job.tool_name}")
    await session.commit()
    return {"id": job.id, "status": "scheduled"}


@router.delete("/jobs/{job_id}", response_model=MessageSchema)
async def delete_job(
    job_id: str, session: AsyncSession = Depends(get_session), user=Depends(current_user)
):
    job = await session.get(CronJob, job_id)
    if not job or job.user_id != user[0].id:
        raise HTTPException(status_code=404, detail="Not found")
    await session.delete(job)
    await session.commit()
    return MessageSchema(detail="deleted")


# --------------------------------------------------------------- settings


@router.get("/settings")
async def get_settings(session: AsyncSession = Depends(get_session), user=Depends(current_user)):
    settings = await session.get(AgentSettings, user[0].id)
    llms = await list_llm_connections(session, user[0].id)
    return {
        "llm_connection_id": settings.llm_connection_id if settings else "",
        "llm_options": [{"id": r.id, "label": r.label, "provider": r.provider, "model": r.model}
                        for r in llms],
    }


class SettingsIn(BaseModel):
    llm_connection_id: str


@router.patch("/settings", response_model=MessageSchema)
async def patch_settings(
    body: SettingsIn, session: AsyncSession = Depends(get_session), user=Depends(current_user)
):
    settings = await session.get(AgentSettings, user[0].id)
    if not settings:
        settings = AgentSettings(user_id=user[0].id)
        session.add(settings)
    settings.llm_connection_id = body.llm_connection_id
    settings.updated_at = utcnow()
    await session.commit()
    return MessageSchema(detail="updated")
