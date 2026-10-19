"""Agent tool registry. Each tool is a validated handler; write-tools use preview→confirm tokens (paper §6)."""
from __future__ import annotations

import json
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    ConfirmToken,
    CronJob,
    Lesson,
    MemoryEdge,
    Notification,
    Proposal,
    ResearchNote,
    Rule,
    Signal,
    Trade,
    User,
    WatchlistItem,
    utcnow,
)
from app.services.agent import trading
from app.services.connections import list_connections as list_broker_connections
from app.services.connections import public_view as broker_public_view
from app.services.llm import list_connections as list_llm_connections
from app.services.llm import public_view as llm_public_view

CONFIRM_TTL_MIN = 15

Handler = Callable[[AsyncSession, User, dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Handler
    needs_confirm: bool = False


def _obj(props: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required}


async def _audit(session: AsyncSession, user: User, action: str, detail: str) -> None:
    await trading.audit(session, user.id, "assistant", action, detail)


async def _pending(
    session: AsyncSession, user: User, tool: str, args: dict[str, Any], summary: str
) -> dict[str, Any]:
    token = secrets.token_urlsafe(16)
    session.add(
        ConfirmToken(
            id=token,
            user_id=user.id,
            tool_name=tool,
            args=json.dumps(args),
            summary=summary[:1000],
            expires_at=utcnow() + timedelta(minutes=CONFIRM_TTL_MIN),
        )
    )
    await _audit(session, user, "confirm_requested", f"{tool}: {summary[:200]}")
    return {
        "status": "needs_confirmation",
        "token": token,
        "summary": summary,
        "expires_minutes": CONFIRM_TTL_MIN,
        "note": "Show this to the user and ask them to Confirm or Reject. The write happens only after they confirm.",
    }


# ------------------------------------------------------------------ handlers


async def h_system_status(session: AsyncSession, user: User, args: dict) -> dict:
    rule = await trading.get_rules(session, user.id)
    open_trades = (
        await session.execute(
            select(Trade).where(Trade.user_id == user.id, Trade.status == "open")
        )
    ).scalars().all()
    today = await session.execute(
        select(Trade).where(
            Trade.user_id == user.id,
            Trade.status == "closed",
            Trade.closed_at >= utcnow().replace(hour=0, minute=0, second=0, microsecond=0),
        )
    )
    today_pnl = sum(t.pnl or 0 for t in today.scalars())
    brokers = [broker_public_view(c) for c in await list_broker_connections(session, user.id)]
    return {
        "mode": rule.mode,
        "autonomy": rule.autonomy,
        "kill_switch": rule.kill_switch,
        "market_open": trading.is_market_hours(),
        "capital": rule.capital,
        "risk_per_trade_pct": rule.risk_per_trade_pct,
        "daily_loss_limit_pct": rule.daily_loss_limit_pct,
        "max_open_positions": rule.max_open_positions,
        "open_positions": len(open_trades),
        "open_trades": [trading.trade_view(t) for t in open_trades],
        "today_realised_pnl": round(today_pnl, 2),
        "broker_connections": [
            {"id": c["id"], "provider": c["provider"], "status": c["status"], "label": c["label"]}
            for c in brokers
        ],
    }


async def h_list_connections(session: AsyncSession, user: User, args: dict) -> dict:
    brokers = [broker_public_view(c) for c in await list_broker_connections(session, user.id)]
    llms = [llm_public_view(r) for r in await list_llm_connections(session, user.id)]
    return {"broker": brokers, "llm": llms}


async def h_get_rules(session: AsyncSession, user: User, args: dict) -> dict:
    r = await trading.get_rules(session, user.id)
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
        "hard_caps_in_code": trading.HARD_CAPS,
        "note": "Live mode and kill switch can ONLY be changed from the website, never by chat.",
    }


async def h_update_rule(session: AsyncSession, user: User, args: dict) -> dict:
    allowed = {
        "capital", "risk_per_trade_pct", "max_open_positions", "daily_loss_limit_pct",
        "max_daily_trades", "instruments_allowed", "notify_on_long", "strategy_id",
    }
    blocked = {"mode", "autonomy", "kill_switch"}
    changes = {k: v for k, v in (args.get("changes") or {}).items() if k in allowed}
    if not changes:
        return {"error": f"No valid fields. Allowed: {sorted(allowed)}. Blocked (website-only): {sorted(blocked)}"}
    clamped, warnings = trading.clamp_rules(changes)
    if "instruments_allowed" in clamped and isinstance(clamped["instruments_allowed"], list):
        clamped["instruments_allowed"] = json.dumps(
            [i for i in clamped["instruments_allowed"] if i in trading.INSTRUMENTS]
        )
    rule = await trading.get_rules(session, user.id)
    old = {k: getattr(rule, k) for k in clamped}
    summary = f"Update rules: {old} → {clamped}" + (f" (warnings: {warnings})" if warnings else "")
    return await _pending(session, user, "update_rule", {"changes": clamped}, summary)


async def h_update_rule_apply(session: AsyncSession, user: User, args: dict) -> dict:
    rule = await trading.get_rules(session, user.id)
    changes = args.get("changes") or {}
    for k, v in changes.items():
        if hasattr(rule, k):
            setattr(rule, k, v)
    rule.updated_at = utcnow()
    await _audit(session, user, "rules_updated", json.dumps(changes))
    return {"status": "updated", "changes": changes}


async def h_read_memory(session: AsyncSession, user: User, args: dict) -> dict:
    kind = args.get("kind", "notes")
    limit = min(int(args.get("limit") or 20), 100)
    if kind == "watchlist":
        rows = (await session.execute(
            select(WatchlistItem).where(WatchlistItem.user_id == user.id).order_by(WatchlistItem.created_at.desc()).limit(limit)
        )).scalars()
        return {"watchlist": [{"id": r.id, "symbol": r.symbol, "notes": r.notes, "source": r.source} for r in rows]}
    if kind == "notes":
        rows = (await session.execute(
            select(ResearchNote).where(ResearchNote.user_id == user.id).order_by(ResearchNote.created_at.desc()).limit(limit)
        )).scalars()
        return {"notes": [
            {"id": r.id, "title": r.title, "body": r.body[:600], "sentiment": r.sentiment,
             "entities": json.loads(r.entities or "[]"), "pinned": r.pinned,
             "created_by": r.created_by, "created_at": r.created_at.isoformat()}
            for r in rows
        ]}
    if kind == "signals":
        rows = (await session.execute(
            select(Signal).where(Signal.user_id == user.id).order_by(Signal.created_at.desc()).limit(limit)
        )).scalars()
        return {"signals": [
            {"id": r.id, "symbol": r.symbol, "direction": r.direction, "catalyst": r.catalyst,
             "score": r.score, "source": r.source, "created_by": r.created_by}
            for r in rows
        ]}
    if kind == "proposals":
        rows = (await session.execute(
            select(Proposal).where(Proposal.user_id == user.id).order_by(Proposal.created_at.desc()).limit(limit)
        )).scalars()
        return {"proposals": [proposal_view(r) for r in rows]}
    if kind == "trades":
        rows = (await session.execute(
            select(Trade).where(Trade.user_id == user.id).order_by(Trade.opened_at.desc()).limit(limit)
        )).scalars()
        return {"trades": [trading.trade_view(r) for r in rows]}
    if kind == "lessons":
        rows = (await session.execute(
            select(Lesson).where(Lesson.user_id == user.id).order_by(Lesson.created_at.desc()).limit(limit)
        )).scalars()
        return {"lessons": [{"id": r.id, "body": r.body, "metric": r.metric} for r in rows]}
    if kind == "audit":
        from app.models import AuditLog

        rows = (await session.execute(
            select(AuditLog).where(AuditLog.user_id == user.id).order_by(AuditLog.created_at.desc()).limit(limit)
        )).scalars()
        return {"audit": [{"id": r.id, "actor": r.actor, "action": r.action, "detail": r.detail[:300],
                           "created_at": r.created_at.isoformat()} for r in rows]}
    return {"error": f"Unknown kind {kind}; use watchlist|notes|signals|proposals|trades|lessons|audit"}


async def h_write_note(session: AsyncSession, user: User, args: dict) -> dict:
    title = (args.get("title") or "").strip()
    if not title:
        return {"error": "title is required"}
    body = (args.get("body") or "").strip()
    entities = [e.upper() for e in (args.get("entities") or [])]
    note = ResearchNote(
        id=uuid.uuid4().hex[:16],
        user_id=user.id,
        title=title[:255],
        body=body[:8000],
        sentiment=args.get("sentiment"),
        entities=json.dumps(entities),
        sources=json.dumps(args.get("sources") or []),
        created_by="assistant",
    )
    session.add(note)
    for e in entities:
        session.add(MemoryEdge(
            user_id=user.id, from_kind="note", from_id=note.id,
            to_kind="entity", to_id=e, rel="mentions",
        ))
    supersedes = args.get("supersedes")
    if supersedes:
        session.add(MemoryEdge(
            user_id=user.id, from_kind="note", from_id=note.id,
            to_kind="note", to_id=str(supersedes), rel="supersedes",
        ))
    await _audit(session, user, "note_written", f"{title[:100]} entities={entities}")
    return {"status": "saved", "note_id": note.id, "entities": entities}


async def h_add_watchlist(session: AsyncSession, user: User, args: dict) -> dict:
    symbol = (args.get("symbol") or "").strip().upper()
    if not symbol:
        return {"error": "symbol is required"}
    existing = (await session.execute(
        select(WatchlistItem).where(WatchlistItem.user_id == user.id, WatchlistItem.symbol == symbol)
    )).scalars().first()
    if existing:
        return {"status": "already_present", "symbol": symbol}
    item = WatchlistItem(
        user_id=user.id, symbol=symbol, notes=(args.get("notes") or "")[:1000], source="user"
    )
    session.add(item)
    await _audit(session, user, "watchlist_added", symbol)
    return {"status": "added", "symbol": symbol}


async def h_add_signal(session: AsyncSession, user: User, args: dict) -> dict:
    symbol = (args.get("symbol") or "").strip().upper()
    if not symbol:
        return {"error": "symbol is required"}
    sig = Signal(
        user_id=user.id,
        symbol=symbol,
        direction=args.get("direction", "long"),
        catalyst=(args.get("catalyst") or "")[:1000],
        score=max(-1.0, min(1.0, float(args.get("score", 0.5)))),
        source=args.get("source", "agent"),
        created_by="assistant",
    )
    session.add(sig)
    await _audit(session, user, "signal_added", f"{symbol} {sig.direction} score={sig.score}")
    return {"status": "saved", "symbol": symbol, "direction": sig.direction}


async def h_get_quote(session: AsyncSession, user: User, args: dict) -> dict:
    symbol = (args.get("symbol") or "").strip().upper()
    if not symbol:
        return {"error": "symbol is required"}
    px, via = await trading.get_quote(session, user.id, symbol)
    if px is None:
        return {"error": f"No quote for {symbol}: {via}. Connect a broker with a valid token."}
    return {"symbol": symbol, "ltp": px, "via": via}


async def h_get_option_chain(session: AsyncSession, user: User, args: dict) -> dict:
    symbol = (args.get("symbol") or "").strip().upper()
    if not symbol:
        return {"error": "symbol is required"}
    expiry = (args.get("expiry") or "").strip()
    return await trading.get_option_chain(session, user.id, symbol, expiry)


async def h_propose_trade(session: AsyncSession, user: User, args: dict) -> dict:
    rule = await trading.get_rules(session, user.id)
    symbol = (args.get("symbol") or "").strip().upper()
    side = (args.get("side") or "").upper()
    instrument = args.get("instrument") or "equity_intraday"
    if not symbol or side not in ("BUY", "SELL"):
        return {"error": "symbol and side (BUY|SELL) are required"}
    open_count = (await session.execute(
        select(Trade).where(Trade.user_id == user.id, Trade.status.in_(["open", "pending_approval"]))
    )).scalars().all()
    open_count = len(open_count)
    today_start = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    closed_today = (await session.execute(
        select(Trade).where(Trade.user_id == user.id, Trade.status == "closed", Trade.closed_at >= today_start)
    )).scalars().all()
    today_pnl = sum(t.pnl or 0 for t in closed_today)
    ok, reason, qty = trading.risk_check(
        rule, open_count, today_pnl, len(closed_today), args
    )
    proposal = Proposal(
        id=uuid.uuid4().hex[:16],
        user_id=user.id,
        symbol=symbol,
        side=side,
        instrument=instrument,
        expiry=(args.get("expiry") or "")[:16],
        strike=(args.get("strike") or "")[:32],
        entry=float(args.get("entry") or 0),
        stop=float(args.get("stop") or 0),
        target=float(args.get("target") or 0),
        qty=qty,
        rationale=(args.get("rationale") or "")[:2000],
        confidence=max(0.0, min(1.0, float(args.get("confidence", 0.5)))),
        source=args.get("source", "agent"),
        mode="live" if rule.mode == "live" else "paper",
        status="vetoed" if not ok else "approved",
        veto_reason="" if ok else reason,
    )
    session.add(proposal)
    await _audit(session, user, "risk_" + ("passed" if ok else "vetoed"), f"{symbol} {side}: {reason}")
    if not ok:
        return {
            "status": "vetoed",
            "proposal_id": proposal.id,
            "reason": reason,
            "note": "Risk Manager rejected this proposal. Report the reason to the user; do not retry with worse risk.",
        }
    trade = await trading.open_trade(
        session, user, rule, proposal.id, symbol, side, instrument, qty,
        proposal.entry, proposal.stop, proposal.target,
        expiry=proposal.expiry, strike=proposal.strike,
    )
    proposal.status = "pending_approval" if trade.status == "pending_approval" else "filled"
    if trade.status == "pending_approval":
        return {
            "status": "pending_broker_approval",
            "proposal_id": proposal.id,
            "trade_id": trade.id,
            "note": "LIVE mode: trade is waiting for per-trade approval on the Trades page of the website.",
        }
    return {"status": "filled_paper" if trade.mode == "paper" else "filled_live",
            "proposal_id": proposal.id, "trade": trading.trade_view(trade)}


async def h_schedule_job(session: AsyncSession, user: User, args: dict) -> dict:
    name = (args.get("name") or "").strip()
    tool_name = (args.get("tool_name") or "").strip()
    if not name or not tool_name:
        return {"error": "name and tool_name are required"}
    interval = max(5, min(int(args.get("interval_minutes") or 60), 24 * 60))
    summary = f"Schedule '{name}' → tool {tool_name} every {interval}m (market_hours_only={bool(args.get('market_hours_only', True))})"
    return await _pending(session, user, "schedule_job", {
        "name": name[:128], "tool_name": tool_name[:64],
        "args": args.get("args") or {}, "interval_minutes": interval,
        "market_hours_only": bool(args.get("market_hours_only", True)),
    }, summary)


async def h_schedule_job_apply(session: AsyncSession, user: User, args: dict) -> dict:
    job = CronJob(
        id=uuid.uuid4().hex[:12],
        user_id=user.id,
        name=args["name"],
        tool_name=args["tool_name"],
        args=json.dumps(args.get("args") or {}),
        interval_minutes=int(args.get("interval_minutes") or 60),
        market_hours_only=bool(args.get("market_hours_only", True)),
    )
    session.add(job)
    await _audit(session, user, "job_scheduled", f"{job.name} → {job.tool_name} /{job.interval_minutes}m")
    return {"status": "scheduled", "job_id": job.id}


async def h_list_jobs(session: AsyncSession, user: User, args: dict) -> dict:
    rows = (await session.execute(
        select(CronJob).where(CronJob.user_id == user.id).order_by(CronJob.created_at.desc())
    )).scalars()
    return {"jobs": [
        {"id": r.id, "name": r.name, "tool_name": r.tool_name, "args": json.loads(r.args or "{}"),
         "interval_minutes": r.interval_minutes, "market_hours_only": r.market_hours_only,
         "enabled": r.enabled, "last_run_at": r.last_run_at.isoformat() if r.last_run_at else None,
         "last_result": r.last_result[:200]}
        for r in rows
    ]}


async def h_delete_job(session: AsyncSession, user: User, args: dict) -> dict:
    job = await session.get(CronJob, str(args.get("job_id") or ""))
    if not job or job.user_id != user.id:
        return {"error": "job not found"}
    summary = f"Delete scheduled job '{job.name}' ({job.tool_name} every {job.interval_minutes}m)"
    return await _pending(session, user, "delete_job", {"job_id": job.id}, summary)


async def h_delete_job_apply(session: AsyncSession, user: User, args: dict) -> dict:
    job = await session.get(CronJob, str(args.get("job_id") or ""))
    if not job:
        return {"error": "job not found"}
    await session.delete(job)
    await _audit(session, user, "job_deleted", str(args.get("job_id")))
    return {"status": "deleted"}


async def h_research_symbol(session: AsyncSession, user: User, args: dict) -> dict:
    symbol = (args.get("symbol") or "").strip().upper()
    if not symbol:
        return {"error": "symbol is required"}
    px, via = await trading.get_quote(session, user.id, symbol)
    notes = (await session.execute(
        select(ResearchNote).where(ResearchNote.user_id == user.id).order_by(ResearchNote.created_at.desc()).limit(50)
    )).scalars()
    matches = [n for n in notes if symbol in json.loads(n.entities or "[]") or symbol.lower() in n.body.lower()]
    sigs = (await session.execute(
        select(Signal).where(Signal.user_id == user.id, Signal.symbol == symbol)
        .order_by(Signal.created_at.desc()).limit(10)
    )).scalars()
    wl = (await session.execute(
        select(WatchlistItem).where(WatchlistItem.user_id == user.id, WatchlistItem.symbol == symbol)
    )).scalars().first()
    return {
        "symbol": symbol,
        "ltp": px,
        "quote_via": via,
        "on_watchlist": bool(wl),
        "watchlist_notes": wl.notes if wl else "",
        "signals": [{"direction": s.direction, "catalyst": s.catalyst, "score": s.score, "by": s.created_by} for s in sigs],
        "notes": [{"id": n.id, "title": n.title, "body": n.body[:400], "sentiment": n.sentiment} for n in matches[:5]],
    }


def proposal_view(p: Proposal) -> dict:
    return {
        "id": p.id, "symbol": p.symbol, "side": p.side, "instrument": p.instrument,
        "expiry": p.expiry, "strike": p.strike, "entry": p.entry, "stop": p.stop,
        "target": p.target, "qty": p.qty, "rationale": p.rationale,
        "confidence": p.confidence, "source": p.source, "status": p.status,
        "veto_reason": p.veto_reason, "mode": p.mode,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


# ----------------------------------------------------------------- registry

TOOLS: dict[str, ToolSpec] = {}


def _reg(spec: ToolSpec) -> None:
    TOOLS[spec.name] = spec


_reg(ToolSpec("get_system_status", "Current trading mode, kill switch, market hours, open trades, today's P&L, broker connection statuses.", _obj({}, []), h_system_status))
_reg(ToolSpec("list_connections", "List broker (Fyers/Groww) and LLM connections with masked keys and auth status.", _obj({}, []), h_list_connections))
_reg(ToolSpec("get_rules", "Read the current trading rules and the hard caps that live in code.", _obj({}, []), h_get_rules))
_reg(ToolSpec("update_rule", "Change trading rules (preview→confirm). Cannot change mode/autonomy/kill_switch — website only. Values are clamped to hard caps.", _obj({
    "changes": {"type": "object", "description": "e.g. {\"risk_per_trade_pct\": 0.5, \"max_open_positions\": 2}"},
}, ["changes"]), h_update_rule, needs_confirm=True))
_reg(ToolSpec("read_memory", "Read shared memory rows the agents and user both see.", _obj({
    "kind": {"type": "string", "enum": ["watchlist", "notes", "signals", "proposals", "trades", "lessons", "audit"]},
    "limit": {"type": "integer", "minimum": 1, "maximum": 100},
}, ["kind"]), h_read_memory))
_reg(ToolSpec("write_note", "Save a research note (linked to entity symbols in the memory graph).", _obj({
    "title": {"type": "string"},
    "body": {"type": "string"},
    "entities": {"type": "array", "items": {"type": "string"}, "description": "stock/sector symbols"},
    "sentiment": {"type": "number", "minimum": -1, "maximum": 1},
    "sources": {"type": "array", "items": {"type": "string"}},
    "supersedes": {"type": "string", "description": "note id this replaces"},
}, ["title"]), h_write_note))
_reg(ToolSpec("add_to_watchlist", "Add a symbol to the user's watchlist.", _obj({
    "symbol": {"type": "string"},
    "notes": {"type": "string"},
}, ["symbol"]), h_add_watchlist))
_reg(ToolSpec("add_signal", "Record a candidate signal (symbol, direction, catalyst, score -1..1).", _obj({
    "symbol": {"type": "string"},
    "direction": {"type": "string", "enum": ["long", "short"]},
    "catalyst": {"type": "string"},
    "score": {"type": "number"},
}, ["symbol"]), h_add_signal))
_reg(ToolSpec("get_quote", "Live LTP quote via the connected broker (Fyers/Groww); falls back to free NSE for indices.", _obj({
    "symbol": {"type": "string"},
}, ["symbol"]), h_get_quote))
_reg(ToolSpec("get_option_chain", "Option chain for an index/underlying (e.g. NIFTY, BANKNIFTY, RELIANCE). Groww needs the ₹499 Trading API subscription; Fyers needs a valid token.", _obj({
    "symbol": {"type": "string"},
    "expiry": {"type": "string", "description": "YYYY-MM-DD; empty = nearest/current expiry"},
}, ["symbol"]), h_get_option_chain))
_reg(ToolSpec("research_symbol", "Aggregate everything known about a symbol: quote, watchlist, signals, research notes.", _obj({
    "symbol": {"type": "string"},
}, ["symbol"]), h_research_symbol))
_reg(ToolSpec("propose_trade", "Propose a trade. Deterministic Risk Manager sizes and vets it. Paper mode fills immediately after passing; live mode waits for website approval. Requires entry, stop and target.", _obj({
    "symbol": {"type": "string"},
    "side": {"type": "string", "enum": ["BUY", "SELL"]},
    "instrument": {"type": "string", "enum": ["equity_intraday", "equity_delivery", "futures", "options"]},
    "entry": {"type": "number"},
    "stop": {"type": "number"},
    "target": {"type": "number"},
    "qty": {"type": "number", "description": "required for futures/options (total units)"},
    "expiry": {"type": "string", "description": "YYYY-MM-DD for F&O"},
    "strike": {"type": "string"},
    "rationale": {"type": "string"},
    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
}, ["symbol", "side", "instrument", "entry", "stop", "target"]), h_propose_trade))
_reg(ToolSpec("schedule_job", "Schedule a repeating tool call (e.g. research_symbol every 30m). preview→confirm.", _obj({
    "name": {"type": "string"},
    "tool_name": {"type": "string"},
    "args": {"type": "object"},
    "interval_minutes": {"type": "integer", "minimum": 5, "maximum": 1440},
    "market_hours_only": {"type": "boolean"},
}, ["name", "tool_name"]), h_schedule_job, needs_confirm=True))
_reg(ToolSpec("list_jobs", "List scheduled jobs.", _obj({}, []), h_list_jobs))
_reg(ToolSpec("delete_job", "Delete a scheduled job. preview→confirm.", _obj({
    "job_id": {"type": "string"},
}, ["job_id"]), h_delete_job, needs_confirm=True))

# apply-handlers are not exposed to the model — they run only from website confirm buttons
CONFIRM_APPLY: dict[str, Handler] = {
    "update_rule": h_update_rule_apply,
    "schedule_job": h_schedule_job_apply,
    "delete_job": h_delete_job_apply,
}


def tool_specs_for_llm() -> list[dict]:
    return [
        {"name": s.name, "description": s.description, "parameters": s.parameters}
        for s in TOOLS.values()
    ]


async def execute_tool(
    session: AsyncSession, user: User, name: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    spec = TOOLS.get(name)
    if not spec:
        return {"error": f"Unknown tool {name}"}
    try:
        result = await spec.handler(session, user, arguments)
        await session.commit()
        return result
    except Exception as exc:  # noqa: BLE001
        await session.rollback()
        return {"error": f"{type(exc).__name__}: {exc}"}


async def run_confirm_token(session: AsyncSession, user: User, token: str) -> dict[str, Any]:
    row = await session.get(ConfirmToken, token)
    if not row or row.user_id != user.id:
        return {"error": "Unknown confirmation token"}
    if row.used:
        return {"error": "Token already used"}
    if row.expires_at.replace(tzinfo=row.expires_at.tzinfo or utcnow().tzinfo) < utcnow():
        return {"error": "Token expired — ask the agent to retry"}
    apply_fn = CONFIRM_APPLY.get(row.tool_name)
    if not apply_fn:
        return {"error": f"No apply handler for {row.tool_name}"}
    row.used = True
    result = await apply_fn(session, user, json.loads(row.args or "{}"))
    await session.commit()
    return result
