"""S5 — background worker agents (paper §4.1 roster).

Phase-1 workers implemented here: scout (code) and reporter (code, incl. memory
expiry). News / Macro / Analyst are LLM workers planned for phase 2 — they appear
in the roster as `planned` until their data sources land.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AgentRun,
    AgentSettings,
    Lesson,
    MemoryEdge,
    ResearchNote,
    Signal,
    Trade,
    WatchlistItem,
    utcnow,
)
from app.services.agent import trading

log = logging.getLogger("igris.workers")

IST = trading.IST
MOVE_THRESHOLD_PCT = 3.0   # watchlist move that tags a signal
WATCHLIST_CAP = 20         # symbols scanned per scout run
DAILY_LESSON_METRIC_PREFIX = "daily:"

# Roster metadata for all nine paper agents (§4.1). kind: llm | code.
WORKER_DEFS: list[dict] = [
    {"name": "chat", "label": "Main chat", "kind": "llm", "family": "memory",
     "schedule": "on demand", "role": "Talks to you, uses tools, previews rule changes"},
    {"name": "scout", "label": "Scout", "kind": "code", "family": "research",
     "schedule": "08:30 pre-open + every 15 min in market hours",
     "role": "Scans watchlist + indices, tags signals"},
    {"name": "news", "label": "News & Sentiment", "kind": "llm", "family": "research",
     "schedule": "every 30 min (07:00–16:00)", "role": "Clusters headlines, scores sentiment",
     "planned": "pending news source (RSS → phase 2)"},
    {"name": "macro", "label": "Global Macro", "kind": "llm", "family": "research",
     "schedule": "08:15 daily", "role": "Overnight world + GIFT Nifty pre-market note",
     "planned": "pending macro feed wiring (phase 2)"},
    {"name": "analyst", "label": "Analyst", "kind": "llm", "family": "research",
     "schedule": "08:45 + hourly in market hours", "role": "Ranks signals, drafts proposals",
     "planned": "pending scheduled LLM batch runs (phase 2)"},
    {"name": "risk", "label": "Risk Manager", "kind": "code", "family": "safety",
     "schedule": "every proposal (always on)", "role": "Sizes, sets stop, vetoes vs rules"},
    {"name": "executor", "label": "Executor", "kind": "code", "family": "safety",
     "schedule": "every approved trade (always on)", "role": "Paper fills / live orders"},
    {"name": "monitor", "label": "Monitor", "kind": "code", "family": "safety",
     "schedule": "every 60 s", "role": "Stop/target exits, EOD square-off"},
    {"name": "reporter", "label": "Reporter", "kind": "code", "family": "review",
     "schedule": "15:35 IST (EOD)", "role": "Daily P&L, lessons, memory expiry"},
]

TOGGLEABLE = {"scout", "news", "macro", "analyst", "reporter"}
DEFAULT_ENABLED = {"scout": True, "news": False, "macro": False, "analyst": False, "reporter": True}
ACTIVE_WORKERS = ("scout", "reporter")   # phase-1 implemented


def as_utc(dt: datetime | None) -> datetime | None:
    """SQLite returns naive datetimes — normalise to aware UTC before comparing."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def enabled_map(settings: AgentSettings | None) -> dict[str, bool]:
    out = dict(DEFAULT_ENABLED)
    if settings and settings.workers_enabled:
        try:
            stored = json.loads(settings.workers_enabled)
            if isinstance(stored, dict):
                for k in TOGGLEABLE:
                    if k in stored:
                        out[k] = bool(stored[k])
        except (ValueError, TypeError):
            pass
    return out


# ------------------------------------------------------------------ due logic


def _ist_today_start(now: datetime) -> datetime:
    t = now.astimezone(IST)
    return t.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


def _due(worker: str, last: datetime | None, now: datetime) -> bool:
    last = as_utc(last)
    t = now.astimezone(IST)
    weekday = t.weekday()
    mins = t.hour * 60 + t.minute
    if worker == "scout":
        if trading.is_market_hours(now):
            return last is None or (now - last) >= timedelta(minutes=15)
        # pre-open window 08:30–09:14 IST, once per day
        if weekday < 5 and 8 * 60 + 30 <= mins < 9 * 60 + 15:
            return last is None or last.astimezone(IST).date() < t.date()
        return False
    if worker == "reporter":
        if weekday >= 5:
            return False
        if mins >= 15 * 60 + 35:
            return last is None or last.astimezone(IST).date() < t.date()
        return False
    return False  # phase-2 workers get schedules when implemented


# ------------------------------------------------------------------ sources


async def _nse_index_snapshot() -> tuple[dict[str, tuple[float, float]], str]:
    """Free NSE indices (+ India VIX). Returns ({name: (last, pct)}, detail)."""
    try:
        from nsepython import nsefetch

        data = nsefetch("https://www.nseindia.com/api/allIndices")
        rows = data.get("data") or [] if isinstance(data, dict) else []
    except Exception as exc:  # noqa: BLE001
        log.debug("nse indices failed: %s", exc)
        return {}, f"index: unavailable ({type(exc).__name__})"
    wanted = ("NIFTY 50", "NIFTY BANK", "NIFTY IT", "NIFTY FINANCIAL SERVICES",
              "NIFTY MIDCAP SELECT", "NIFTY AUTO", "NIFTY PHARMA", "INDIA VIX")
    out: dict[str, tuple[float, float]] = {}
    for r in rows:
        name = r.get("index")
        if name in wanted and name not in out:
            try:
                out[name] = (float(r.get("last") or 0), float(r.get("percentChange") or 0))
            except (TypeError, ValueError):
                continue
    nifty = out.get("NIFTY 50")
    vix = out.get("INDIA VIX")
    parts = []
    if nifty:
        parts.append(f"NIFTY 50 {nifty[0]:,.0f} ({nifty[1]:+.2f}%)")
    if vix:
        parts.append(f"VIX {vix[0]:.1f}")
    return out, (" · ".join(parts) if parts else "index: no data")


def _fyers_symbol(sym: str) -> str:
    return f"NSE:{sym}-EQ"


def _parse_fyers_ticker(raw: str | None, fallback: str) -> str:
    # "NSE:RELIANCE-EQ" -> "RELIANCE"
    if not raw:
        return fallback
    part = raw.split(":")[-1]
    return part.removesuffix("-EQ").strip() or fallback


async def fetch_quotes(
    session: AsyncSession, user_id: int, symbols: list[str]
) -> dict[str, tuple[float, float | None]]:
    """{symbol: (ltp, prev_close|None)} via Fyers batch then Groww per-symbol."""
    out: dict[str, tuple[float, float | None]] = {}
    if not symbols:
        return out

    client, _ = trading._broker_client(session, user_id, "fyers")
    if client is not None:
        try:
            resp = client.quotes({"symbols": ",".join(_fyers_symbol(s) for s in symbols)})
            if isinstance(resp, dict) and resp.get("s") == "ok":
                for i, d in enumerate(resp.get("d") or []):
                    if not isinstance(d, dict) or d.get("s") not in (None, "ok"):
                        continue
                    v = d.get("v") or {}
                    lp = v.get("lp") or v.get("ltp")
                    if not lp:
                        continue
                    prev = v.get("ep") or v.get("prev_close") or v.get("prevClosePrice")
                    ticker = _parse_fyers_ticker(
                        d.get("symbol") or v.get("symbol"),
                        symbols[i] if i < len(symbols) else "",
                    )
                    if ticker in symbols:
                        try:
                            out[ticker] = (float(lp), float(prev) if prev else None)
                        except (TypeError, ValueError):
                            out[ticker] = (float(lp), None)
        except Exception as exc:  # noqa: BLE001
            log.debug("fyers batch quotes failed: %s", exc)

    missing = [s for s in symbols if s not in out][:WATCHLIST_CAP]
    if missing:
        client, _ = trading._broker_client(session, user_id, "groww")
        if client is not None:
            for sym in missing:
                try:
                    resp = client.get_quote(trading_symbol=sym, exchange="NSE")
                    p = resp.get("payload") or resp.get("data") or {}
                    ltp = p.get("ltp")
                    if ltp:
                        ohlc = p.get("ohlc") or {}
                        prev = ohlc.get("close")
                        out[sym] = (float(ltp), float(prev) if prev else None)
                except Exception as exc:  # noqa: BLE001
                    log.debug("groww quote %s failed: %s", sym, exc)
    return out


# ------------------------------------------------------------------ workers


async def run_scout(
    session: AsyncSession, user_id: int, now: datetime | None = None,
    quotes_fn=None,
) -> tuple[int, str]:
    """Scan watchlist + indices → signals. Returns (rows_written, detail)."""
    now = now or utcnow()
    today_start = _ist_today_start(now)
    watch = list((await session.execute(
        select(WatchlistItem).where(WatchlistItem.user_id == user_id)
        .order_by(WatchlistItem.id).limit(WATCHLIST_CAP)
    )).scalars())
    symbols = [w.symbol for w in watch]

    quotes = await (quotes_fn or fetch_quotes)(session, user_id, symbols)

    # dedup: scout signals already written today for these symbols
    seen = set((await session.execute(
        select(Signal.symbol).where(
            Signal.user_id == user_id,
            Signal.created_by == "scout",
            Signal.created_at >= today_start,
        )
    )).scalars())

    day_close = now.astimezone(IST).replace(
        hour=15, minute=30, second=0, microsecond=0
    ).astimezone(timezone.utc)
    rows = 0
    moves: list[str] = []
    for sym, (ltp, prev) in quotes.items():
        if not prev or prev <= 0:
            continue
        pct = (ltp - prev) / prev * 100
        if abs(pct) < MOVE_THRESHOLD_PCT or sym in seen:
            continue
        direction = "long" if pct > 0 else "short"
        session.add(Signal(
            user_id=user_id, symbol=sym, direction=direction,
            catalyst=f"scout: {sym} {pct:+.1f}% vs prev close (₹{prev:,.2f} → ₹{ltp:,.2f})",
            score=min(0.9, round(0.5 + abs(pct) / 20, 2)),
            source="agent", created_by="scout", expires_at=day_close,
        ))
        rows += 1
        moves.append(f"{sym} {pct:+.1f}%")

    _, index_detail = await _nse_index_snapshot()
    quoted = len(quotes)
    detail = (
        f"{index_detail} · watchlist {quoted}/{len(symbols)} quoted"
        + (f" · signals: {', '.join(moves)}" if moves else " · no big moves")
    )
    if rows:
        await trading.audit(session, user_id, "scout", "signals_tagged",
                            f"{rows} signals: {', '.join(moves)}")
    return rows, detail


async def run_reporter(session: AsyncSession, user_id: int, now: datetime | None = None) -> tuple[int, str]:
    """EOD roll-up: daily lesson + rolling stats + memory expiry."""
    now = now or utcnow()
    rows = 0
    rows, detail = await run_expiry(session, user_id, now=now)

    today_start = _ist_today_start(now)
    closed = list((await session.execute(
        select(Trade).where(
            Trade.user_id == user_id, Trade.status == "closed",
            Trade.closed_at >= today_start,
        )
    )).scalars())
    if not closed:
        return rows, f"{detail} · reporter: no closed trades today"

    day_key = now.astimezone(IST).date().isoformat()
    metric = DAILY_LESSON_METRIC_PREFIX + day_key
    exists = (await session.execute(
        select(Lesson.id).where(Lesson.user_id == user_id, Lesson.metric == metric)
    )).first()

    net = sum(t.pnl or 0 for t in closed)
    wins = sum(1 for t in closed if (t.pnl or 0) > 0)
    body = (
        f"{day_key}: {len(closed)} closed · {wins} wins · net ₹{net:,.0f} "
        f"(win rate {wins * 100 // max(len(closed), 1)}%)"
    )
    if not exists:
        session.add(Lesson(user_id=user_id, body=body, metric=metric))
        rows += 1

    # rolling 30-trade stats (kept as one updated row, paper §10)
    recent = list((await session.execute(
        select(Trade).where(Trade.user_id == user_id, Trade.status == "closed")
        .order_by(Trade.closed_at.desc()).limit(30)
    )).scalars())
    if recent:
        pnls = [t.pnl or 0 for t in recent]
        w = sum(1 for p in pnls if p > 0)
        rolling_body = (
            f"Last {len(recent)} closed: {w} wins ({w * 100 // len(recent)}%) · "
            f"expectancy ₹{sum(pnls) / len(pnls):,.0f}/trade · net ₹{sum(pnls):,.0f}"
        )
        row = (await session.execute(
            select(Lesson).where(Lesson.user_id == user_id, Lesson.metric == "rolling30")
        )).scalars().first()
        if row:
            row.body = rolling_body
            row.created_at = utcnow()
        else:
            session.add(Lesson(user_id=user_id, body=rolling_body, metric="rolling30"))
        rows += 1

    return rows, f"{detail} · reporter: {body}"


async def run_expiry(session: AsyncSession, user_id: int, now: datetime | None = None) -> tuple[int, str]:
    """Expire intraday notes/signals (paper §5.3). Pinned notes survive."""
    now = now or utcnow()
    expired_notes = list((await session.execute(
        select(ResearchNote).where(
            ResearchNote.user_id == user_id,
            ResearchNote.expires_at.is_not(None),
            ResearchNote.expires_at <= now,
            ResearchNote.pinned == False,  # noqa: E712
        )
    )).scalars())
    expired_signals = list((await session.execute(
        select(Signal).where(
            Signal.user_id == user_id,
            Signal.expires_at.is_not(None),
            Signal.expires_at <= now,
        )
    )).scalars())
    note_ids = [n.id for n in expired_notes]
    signal_ids = [str(s.id) for s in expired_signals]
    n = len(note_ids) + len(signal_ids)
    if not n:
        return 0, "expiry: nothing stale"

    for kind, ids in (("note", note_ids), ("signal", signal_ids)):
        if ids:
            await session.execute(delete(MemoryEdge).where(
                MemoryEdge.user_id == user_id, MemoryEdge.from_kind == kind,
                MemoryEdge.from_id.in_(ids),
            ))
            await session.execute(delete(MemoryEdge).where(
                MemoryEdge.user_id == user_id, MemoryEdge.to_kind == kind,
                MemoryEdge.to_id.in_(ids),
            ))
    for sig in expired_signals:
        await session.delete(sig)
    for note in expired_notes:
        await session.delete(note)
    return n, f"expiry: removed {len(note_ids)} notes, {len(signal_ids)} signals"


# ------------------------------------------------------------------ scheduler


async def _last_run(session: AsyncSession, user_id: int, worker: str) -> datetime | None:
    row = (await session.execute(
        select(AgentRun.started_at).where(
            AgentRun.user_id == user_id, AgentRun.worker == worker
        ).order_by(AgentRun.started_at.desc()).limit(1)
    )).first()
    return as_utc(row[0]) if row else None


async def tick(session: AsyncSession, user_id: int, now: datetime | None = None) -> None:
    """Run due phase-1 workers for one user; record AgentRun rows."""
    now = now or utcnow()
    settings = await session.get(AgentSettings, user_id)
    enabled = enabled_map(settings)
    for worker in ACTIVE_WORKERS:
        if not enabled.get(worker, True):
            continue
        last = await _last_run(session, user_id, worker)
        if not _due(worker, last, now):
            continue
        run = AgentRun(user_id=user_id, worker=worker, started_at=now)
        session.add(run)
        try:
            if worker == "scout":
                rows, detail = await run_scout(session, user_id, now=now)
            else:
                rows, detail = await run_reporter(session, user_id, now=now)
            run.status = "ok"
            run.rows_written = rows
            run.detail = detail[:2000]
        except Exception as exc:  # noqa: BLE001
            run.status = "error"
            run.detail = f"{type(exc).__name__}: {exc}"[:2000]
            log.warning("worker %s failed for user %s: %s", worker, user_id, exc)
        run.finished_at = utcnow()
        try:
            await session.commit()
        except Exception:  # noqa: BLE001
            await session.rollback()
            log.warning("worker %s commit failed for user %s", worker, user_id)
