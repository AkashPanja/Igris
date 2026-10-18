"""S4 trading core: Risk Manager (code), paper engine, executor, monitor, costs.

Deterministic only — no LLM calls here (paper §4.2: exact numbers come from code).
"""
from __future__ import annotations

import json
import math
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AuditLog,
    Connection,
    Notification,
    Rule,
    Trade,
    User,
    utcnow,
)
from app.services.connections import load_credentials

IST = timezone(timedelta(hours=5, minutes=30))

# Hard caps live in code — neither DB, chat nor agent can write these (paper §6.3)
HARD_CAPS = {
    "max_risk_per_trade_pct": 2.0,
    "max_open_positions": 5,
    "max_daily_loss_limit_pct": 3.0,
    "max_daily_trades": 30,
    "stop_may_only_tighten": True,
    "stop_required": True,
}

# Simplified but honest cost model (INR); STT reflects Apr-2026 rates
COSTS = {
    "brokerage_per_order": 20.0,
    "stt": {  # sell-side unless noted
        "equity_intraday": 0.00025,
        "equity_delivery": 0.001,  # both sides
        "futures": 0.0005,
        "options": 0.0015,  # on premium
    },
    "exchange_txn": 0.000029,
    "gst_on_fees": 0.18,
    "slippage_bps": {"equity_intraday": 5, "equity_delivery": 0, "futures": 10, "options": 10},
}

INSTRUMENTS = ["equity_intraday", "equity_delivery", "futures", "options"]


def is_market_hours(now: datetime | None = None) -> bool:
    t = (now or datetime.now(timezone.utc)).astimezone(IST)
    if t.weekday() >= 5:
        return False
    mins = t.hour * 60 + t.minute
    return 9 * 60 + 15 <= mins <= 15 * 60 + 30


def is_squre_off_time(now: datetime | None = None) -> bool:
    t = (now or datetime.now(timezone.utc)).astimezone(IST)
    return 15 * 60 + 15 <= t.hour * 60 + t.minute <= 15 * 60 + 30


def default_rules(user_id: int) -> Rule:
    return Rule(user_id=user_id)


async def get_rules(session: AsyncSession, user_id: int) -> Rule:
    rule = await session.get(Rule, user_id)
    if not rule:
        rule = default_rules(user_id)
        session.add(rule)
        await session.commit()
        await session.refresh(rule)
    return rule


def clamp_rules(data: dict[str, Any]) -> dict[str, Any]:
    """Clamp user/agent edits to hard caps. Returns (clamped, warnings)."""
    warnings: list[str] = []
    out = dict(data)

    def _clamp(key: str, cap: float) -> None:
        if key in out and out[key] is not None:
            try:
                v = float(out[key])
            except (TypeError, ValueError):
                out.pop(key, None)
                return
            if v > cap:
                warnings.append(f"{key} clamped to hard cap {cap}")
                out[key] = cap
            elif v < 0:
                out.pop(key, None)

    _clamp("risk_per_trade_pct", HARD_CAPS["max_risk_per_trade_pct"])
    _clamp("daily_loss_limit_pct", HARD_CAPS["max_daily_loss_limit_pct"])
    _clamp("max_open_positions", HARD_CAPS["max_open_positions"])
    _clamp("max_daily_trades", HARD_CAPS["max_daily_trades"])
    return out, warnings


async def audit(session: AsyncSession, user_id: int, actor: str, action: str, detail: str = "") -> None:
    session.add(AuditLog(user_id=user_id, actor=actor, action=action, detail=detail[:4000]))


async def notify(
    session: AsyncSession,
    user: User,
    kind: str,
    title: str,
    body: str = "",
    email: bool = False,
) -> None:
    session.add(Notification(user_id=user.id, kind=kind, title=title[:255], body=body[:4000]))
    if email and user.email:
        try:
            from app.services.email import send_email

            await send_email(user.email, title, body)
        except Exception:  # noqa: BLE001 — notifications must not break trading
            pass


def trade_view(t: Trade) -> dict[str, Any]:
    return {
        "id": t.id,
        "proposal_id": t.proposal_id,
        "symbol": t.symbol,
        "side": t.side,
        "instrument": t.instrument,
        "expiry": t.expiry,
        "strike": t.strike,
        "mode": t.mode,
        "qty": t.qty,
        "entry_px": t.entry_px,
        "exit_px": t.exit_px,
        "slippage": t.slippage,
        "costs": t.costs,
        "pnl": t.pnl,
        "status": t.status,
        "exit_reason": t.exit_reason,
        "broker_order_id": t.broker_order_id,
        "is_long": t.side == "BUY",
        "opened_at": t.opened_at.isoformat() if t.opened_at else None,
        "closed_at": t.closed_at.isoformat() if t.closed_at else None,
    }


def compute_costs(instrument: str, side: str, qty: float, price: float) -> float:
    turnover = qty * price
    stt_rate = COSTS["stt"].get(instrument, 0.0)
    stt = turnover * stt_rate
    if instrument == "equity_delivery":
        stt = turnover * stt_rate  # already both-sides blended approximation
    fees = COSTS["brokerage_per_order"] + turnover * COSTS["exchange_txn"]
    gst = fees * COSTS["gst_on_fees"]
    return round(stt + fees + gst, 2)


def apply_slippage(instrument: str, side: str, price: float) -> tuple[float, float]:
    bps = COSTS["slippage_bps"].get(instrument, 5) / 10000.0
    if side == "BUY":
        px = price * (1 + bps)
    else:
        px = price * (1 - bps)
    return round(px, 2), round(abs(px - price), 2)


# ------------------------------------------------------------- risk manager


def risk_check(
    rule: Rule,
    open_count: int,
    today_pnl: float,
    today_trade_count: int,
    proposal: dict[str, Any],
    market_open: bool | None = None,
) -> tuple[bool, str, float]:
    """Pure-function Risk Manager. Returns (ok, reason, sized_qty)."""
    if rule.kill_switch:
        return False, "Kill switch engaged", 0.0
    if proposal.get("instrument") not in json.loads(rule.instruments_allowed or "[]"):
        return False, f"Instrument {proposal.get('instrument')} not allowed by rules", 0.0
    if market_open is None:
        market_open = is_market_hours()
    if not market_open:
        return False, "Market closed — new entries blocked", 0.0
    if open_count >= rule.max_open_positions:
        return False, f"Max open positions reached ({rule.max_open_positions})", 0.0
    if today_trade_count >= rule.max_daily_trades:
        return False, f"Max daily trades reached ({rule.max_daily_trades})", 0.0
    loss_limit = rule.capital * rule.daily_loss_limit_pct / 100.0
    if today_pnl <= -loss_limit:
        return False, f"Daily loss limit hit ({today_pnl:.0f} <= -{loss_limit:.0f})", 0.0

    entry = float(proposal.get("entry") or 0)
    stop = float(proposal.get("stop") or 0)
    side = proposal.get("side")
    if entry <= 0 or stop <= 0:
        return False, "Entry and stop are required", 0.0
    if HARD_CAPS["stop_required"] and not stop:
        return False, "Stop-loss cannot be removed", 0.0
    if side == "BUY" and stop >= entry:
        return False, "For BUY, stop must be below entry", 0.0
    if side == "SELL" and stop <= entry:
        return False, "For SELL, stop must be above entry", 0.0

    risk_amount = rule.capital * rule.risk_per_trade_pct / 100.0
    per_unit = abs(entry - stop)
    instrument = proposal.get("instrument")
    if instrument in ("futures", "options"):
        qty = float(proposal.get("qty") or 0)
        if qty <= 0:
            return False, "F&O proposals must include qty (lots × lot size)", 0.0
        if qty * per_unit > risk_amount * 2:
            return False, (
                f"F&O risk {qty * per_unit:.0f} exceeds 2× per-trade cap {risk_amount:.0f}"
            ), 0.0
        return True, "passed", qty
    qty = math.floor(risk_amount / per_unit)
    if qty <= 0:
        return False, "Position size rounds to zero", 0.0
    return True, "passed", float(qty)


# ---------------------------------------------------------------- executor


async def _broker_client(session: AsyncSession, user_id: int, provider: str):
    """Return (client, accessor) for a connected broker, or (None, error)."""
    result = await session.execute(
        select(Connection).where(Connection.user_id == user_id, Connection.provider == provider)
    )
    conn = result.scalars().first()
    if not conn:
        return None, f"No {provider} connection"
    if conn.status != "connected":
        return None, f"{provider} not connected ({conn.status})"
    creds = load_credentials(conn)
    token = creds.get("access_token") or ""
    if not token:
        return None, f"{provider} has no access token"
    if provider == "fyers":
        from app.services.brokers.fyers import client as fyers_client

        return fyers_client(conn.app_id, token), None
    if provider == "groww":
        from app.services.brokers.groww import client as groww_client

        return groww_client(token), None
    return None, f"Unknown broker {provider}"


async def get_quote(session: AsyncSession, user_id: int, symbol: str) -> tuple[float | None, str]:
    """Best-effort quote via Fyers then Groww. Fail-closed: (None, reason)."""
    client, err = await _broker_client(session, user_id, "fyers")
    if client is not None:
        try:
            resp = client.quotes({"symbols": symbol})
            if isinstance(resp, dict) and resp.get("s") == "ok":
                d = (resp.get("d") or [{}])[0]
                v = d.get("v") or {}
                ltp = v.get("lp") or v.get("ltp")
                if ltp:
                    return float(ltp), "fyers"
        except Exception:  # noqa: BLE001
            pass
    client, err = await _broker_client(session, user_id, "groww")
    if client is not None:
        try:
            resp = client.get_ltp_data(symbols=[symbol])
            data = resp.get("payload") or {}
            for v in data.values():
                if isinstance(v, dict) and v.get("ltp"):
                    return float(v["ltp"]), "groww"
        except Exception:  # noqa: BLE001
            pass
    return None, err or "no quote source"


async def place_broker_order(
    session: AsyncSession, user_id: int, trade: Trade, rule: Rule
) -> tuple[bool, str]:
    """Live order placement. Untested against real capital — approve-each by default."""
    client, err = await _broker_client(session, user_id, "groww")
    if client is not None:
        try:
            # groww trading_symbol like "NIFTY16OCT82500CE" / "RELIANCE"; exchange NSE, segment CASH/CURRENCY per symbol
            segment = "CASH" if trade.instrument.startswith("equity") else ("FNO" if trade.instrument in ("futures", "options") else "CASH")
            resp = client.place_order(
                validity="DAY",
                exchange="NSE",
                order_type="MARKET",
                product="MIS" if trade.instrument == "equity_intraday" else "CNC",
                quantity=int(trade.qty),
                segment=segment,
                trading_symbol=trade.symbol,
                transaction_type=trade.side,
                order_reference_id=trade.id,
            )
            payload = resp.get("payload") or {}
            order_id = str(payload.get("order_number") or payload.get("order_id") or "")
            if order_id:
                return True, order_id
            return False, str(resp)[:300]
        except Exception as exc:  # noqa: BLE001
            return False, f"groww: {exc}"
    client, err = await _broker_client(session, user_id, "fyers")
    if client is not None:
        try:
            data = {
                "symbol": trade.symbol,
                "qty": int(trade.qty),
                "type": 1,  # market
                "side": 1 if trade.side == "BUY" else -1,
                "productType": "INTRADAY" if trade.instrument == "equity_intraday" else "CNC",
                "validity": "DAY",
                "offlineOrder": False,
            }
            resp = client.place_order(data)
            if isinstance(resp, dict) and resp.get("s") == "ok":
                return True, str(resp.get("id", ""))
            return False, str(resp)[:300]
        except Exception as exc:  # noqa: BLE001
            return False, f"fyers: {exc}"
    return False, err or "no broker available"


async def open_trade(
    session: AsyncSession,
    user: User,
    rule: Rule,
    proposal_id: str,
    symbol: str,
    side: str,
    instrument: str,
    qty: float,
    entry: float,
    stop: float,
    target: float,
    expiry: str = "",
    strike: str = "",
) -> Trade:
    """Create a trade record. Paper: filled immediately. Live: approval or auto."""
    fill_px, slip = apply_slippage(instrument, side, entry)
    mode = "live" if rule.mode == "live" else "paper"
    t = Trade(
        id=uuid.uuid4().hex[:16],
        user_id=user.id,
        proposal_id=proposal_id,
        symbol=symbol,
        side=side,
        instrument=instrument,
        expiry=expiry,
        strike=strike,
        mode=mode,
        qty=qty,
        entry_px=fill_px,
        stop_px=stop,
        target_px=target,
        slippage=slip,
        costs=compute_costs(instrument, side, qty, fill_px) if mode == "paper" else 0.0,
        status="open",
        strategy_id=rule.strategy_id,
    )
    if mode == "live":
        if rule.autonomy == "live_approve":
            t.status = "pending_approval"
            t.entry_px = entry
            t.slippage = 0.0
        elif rule.autonomy == "live_auto":
            ok, ref = await place_broker_order(session, user.id, t, rule)
            if not ok:
                t.status = "rejected"
                await audit(session, user.id, "executor", "live_order_failed", f"{symbol}: {ref}")
            else:
                t.broker_order_id = ref
    session.add(t)
    await audit(
        session, user.id, "executor",
        f"trade_opened_{t.status}",
        json.dumps(trade_view(t)),
    )
    if side == "BUY" and rule.notify_on_long:
        await notify(
            session, user, "long_trade",
            f"Long {symbol} ({instrument}, {t.mode})",
            f"{side} {qty} @ {fill_px} · stop {stop} · target {target}",
            email=True,
        )
    return t


async def close_trade(
    session: AsyncSession,
    trade: Trade,
    exit_px: float,
    reason: str,
) -> Trade:
    px, slip = apply_slippage(trade.instrument, trade.side, exit_px)
    gross = (px - trade.entry_px) * trade.qty * (1 if trade.side == "BUY" else -1)
    costs = trade.costs + (compute_costs(trade.instrument, trade.side, trade.qty, px) if trade.mode == "paper" else 0.0)
    trade.exit_px = px
    trade.slippage = trade.slippage + slip
    trade.costs = round(costs, 2)
    trade.pnl = round(gross - costs, 2)
    trade.status = "closed"
    trade.exit_reason = reason
    trade.closed_at = utcnow()
    await audit(session, trade.user_id, "monitor", f"trade_closed_{reason}", json.dumps(trade_view(trade)))
    return trade


async def approve_trade(session: AsyncSession, trade: Trade, rule: Rule) -> tuple[bool, str]:
    if trade.status != "pending_approval":
        return False, f"Not pending approval ({trade.status})"
    ok, ref = await place_broker_order(session, trade.user_id, trade, rule)
    if not ok:
        trade.status = "rejected"
        await audit(session, trade.user_id, "executor", "live_order_failed", ref[:500])
        return False, ref
    trade.status = "open"
    trade.broker_order_id = ref
    await audit(session, trade.user_id, "executor", "live_order_placed", f"{trade.symbol} {trade.side} {trade.qty} ref={ref}")
    return True, ref


async def kill_switch_halt(session: AsyncSession, user: User, rule: Rule) -> int:
    """Halt: flip kill switch, close open paper trades, cancel pending approvals."""
    rule.kill_switch = True
    rule.mode = "paper"
    result = await session.execute(
        select(Trade).where(Trade.user_id == user.id, Trade.status.in_(["open", "pending_approval"]))
    )
    n = 0
    for t in result.scalars():
        if t.status == "pending_approval":
            t.status = "rejected"
            t.exit_reason = "kill"
        else:
            await close_trade(session, t, t.entry_px, "kill")
        n += 1
    await audit(session, user.id, "system", "kill_switch", f"halted {n} trades; mode forced to paper")
    await notify(session, user, "kill", "Kill switch engaged", f"{n} trades halted; mode forced to paper", email=True)
    return n


# ------------------------------------------------------------------ monitor


async def monitor_tick(session: AsyncSession, user: User, rule: Rule) -> dict[str, int]:
    """One deterministic pass: EOD square-off + stop/target exits for open paper trades."""
    stats = {"checked": 0, "closed": 0, "skipped": 0}
    if rule.kill_switch:
        return stats
    result = await session.execute(
        select(Trade).where(Trade.user_id == user.id, Trade.status == "open", Trade.mode == "paper")
    )
    trades = list(result.scalars())
    eod = is_squre_off_time()
    for t in trades:
        stats["checked"] += 1
        if eod:
            quote, _ = await get_quote(session, user.id, t.symbol)
            await close_trade(session, t, quote if quote else t.entry_px, "eod")
            stats["closed"] += 1
            continue
        quote, _ = await get_quote(session, user.id, t.symbol)
        if quote is None:
            stats["skipped"] += 1  # fail closed — no new data, no exit
            continue
        if t.side == "BUY":
            if t.stop_px and quote <= t.stop_px:
                await close_trade(session, t, quote, "stop")
                stats["closed"] += 1
            elif t.target_px and quote >= t.target_px:
                await close_trade(session, t, quote, "target")
                stats["closed"] += 1
        else:
            if t.stop_px and quote >= t.stop_px:
                await close_trade(session, t, quote, "stop")
                stats["closed"] += 1
            elif t.target_px and quote <= t.target_px:
                await close_trade(session, t, quote, "target")
                stats["closed"] += 1
    return stats
