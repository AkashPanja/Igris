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


# ------------------------------------------------------- broker symbol formats
# Verified against official docs 2026-10-19:
#   Fyers: equity "NSE:RELIANCE-EQ"; index "NSE:NIFTY50-INDEX";
#          options monthly "NSE:NIFTY26OCT24000CE", weekly "NSE:NIFTY26102424000CE"
#          (yy + 3-letter-mon monthly; yy+single-digit-month+dd weekly); futures "NSE:NIFTY26OCTFUT"
#   Groww: trading_symbol for F&O monthly-style "NIFTY25OCT24000CE" / futures "NIFTY25OCTFUT";
#          equity plain "RELIANCE"; segment CASH|FNO, product CNC|MIS|NRML

_MON3 = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")
# Common NSE index aliases → canonical Fyers base name (without -INDEX)
_INDEX_ALIASES = {
    "NIFTY": "NIFTY50", "NIFTY50": "NIFTY50", "NIFTY 50": "NIFTY50", "NIFTY-50": "NIFTY50",
    "BANKNIFTY": "BANKNIFTY", "NIFTY BANK": "BANKNIFTY", "NIFTYBANK": "BANKNIFTY",
    "FINNIFTY": "FINNIFTY", "NIFTY FINANCIAL SERVICES": "FINNIFTY", "NIFTY FIN SERVICE": "FINNIFTY",
    "MIDCPNIFTY": "MIDCPNIFTY", "NIFTY MIDCAP SELECT": "MIDCPNIFTY",
    "NIFTY IT": "NIFTYIT", "NIFTYIT": "NIFTYIT",
    "INDIA VIX": "INDIAVIX", "INDIAVIX": "INDIAVIX", "VIX": "INDIAVIX",
    "SENSEX": "SENSEX", "BANKEX": "BANKEX",
    "GIFT NIFTY": "GIFTNIFTY", "GIFTNIFTY": "GIFTNIFTY", "NIFTY SGX": "GIFTNIFTY",
}


def is_index_symbol(sym: str) -> bool:
    return (sym or "").strip().upper() in _INDEX_ALIASES


def fyers_spot_symbol(sym: str) -> str:
    """Map a bare ticker/index to Fyers spot symbol format."""
    key = (sym or "").strip().upper()
    if ":" in key:
        return key
    idx = _INDEX_ALIASES.get(key)
    if idx:
        return f"NSE:{idx}-INDEX"
    return f"NSE:{key}-EQ"


def nse_index_ltp(sym: str) -> float | None:
    """Free NSE index LTP (works from this server IP). Returns None on miss/fail."""
    key = (sym or "").strip().upper()
    canon = _INDEX_ALIASES.get(key)
    if not canon:
        return None
    try:
        from nsepython import nsefetch

        data = nsefetch("https://www.nseindia.com/api/allIndices")
        rows = (data or {}).get("data") or []
        # canonical → the NSE "index" display name(s)
        want = {
            "NIFTY50": "NIFTY 50", "BANKNIFTY": "NIFTY BANK", "FINNIFTY": "NIFTY FINANCIAL SERVICES",
            "MIDCPNIFTY": "NIFTY MIDCAP SELECT", "NIFTYIT": "NIFTY IT", "INDIAVIX": "INDIA VIX",
            "SENSEX": "SENSEX", "BANKEX": "BANKEX",
        }.get(canon, canon)
        for r in rows:
            if (r.get("index") or "").upper() == want.upper():
                ltp = r.get("last")
                if ltp:
                    return float(ltp)
        # GIFT NIFTY isn't in allIndices — it's under marketStatus.giftnifty (LASTPRICE key)
        if canon == "GIFTNIFTY":
            ms = nsefetch("https://www.nseindia.com/api/marketStatus")
            g = (ms or {}).get("giftnifty") or {}
            ltp = g.get("LASTPRICE") or g.get("last") or g.get("latest")
            if ltp:
                return float(ltp)
    except Exception:  # noqa: BLE001
        return None
    return None


def _parse_expiry(expiry: str) -> datetime | None:
    try:
        return datetime.strptime((expiry or "").strip()[:10], "%Y-%m-%d")
    except ValueError:
        return None


def _is_monthly_expiry(d: datetime) -> bool:
    """True when d is the month's last Tuesday or Thursday (NSE monthly expiry days)."""
    import calendar

    last_day = calendar.monthrange(d.year, d.month)[1]
    for dow in (1, 3):  # Tue=1, Thu=3
        dd = last_day
        while datetime(d.year, d.month, dd).weekday() != dow:
            dd -= 1
        if dd == d.day:
            return True
    return False


def _split_strike_ot(raw_strike: str) -> tuple[str, str]:
    """'24000CE' → ('24000','CE'); '24000' → ('24000','')."""
    s = (raw_strike or "").strip().upper()
    if s.endswith(("CE", "PE")):
        return s[:-2], s[-2:]
    return s, ""


def fyers_contract_symbol(underlying: str, instrument: str, expiry: str, raw_strike: str = "") -> str:
    """Build a Fyers F&O symbol; falls back to equity spot when expiry unparseable."""
    d = _parse_expiry(expiry)
    if d is None:
        return fyers_spot_symbol(underlying)
    yy = f"{d.year % 100:02d}"
    mon = _MON3[d.month - 1]
    if instrument == "futures":
        return f"NSE:{underlying}{yy}{mon}FUT"
    strike, ot = _split_strike_ot(raw_strike)
    if not strike or not ot:
        return fyers_spot_symbol(underlying)  # can't build a contract without strike+CE/PE
    token = f"{yy}{mon}" if _is_monthly_expiry(d) else f"{yy}{d.month}{d.day:02d}"
    return f"NSE:{underlying}{token}{strike}{ot}"


def groww_contract_symbol(underlying: str, instrument: str, expiry: str, raw_strike: str = "") -> str:
    """Build a Groww F&O trading_symbol (monthly-style) or return the equity ticker."""
    if instrument.startswith("equity"):
        return underlying
    d = _parse_expiry(expiry)
    if d is None:
        return underlying
    yy = f"{d.year % 100:02d}"
    mon = _MON3[d.month - 1]
    if instrument == "futures":
        return f"{underlying}{yy}{mon}FUT"
    strike, ot = _split_strike_ot(raw_strike)
    if not strike or not ot:
        return underlying
    return f"{underlying}{yy}{mon}{strike}{ot}"


def groww_product(instrument: str) -> str:
    """Groww product per docs: F&O=NRML, equity_intraday=MIS, else CNC."""
    if instrument in ("futures", "options"):
        return "NRML"
    if instrument == "equity_intraday":
        return "MIS"
    return "CNC"


async def get_quote(session: AsyncSession, user_id: int, symbol: str) -> tuple[float | None, str]:
    """Best-effort quote: Fyers → Groww → free NSE (indices only).

    Accepts "TNPO", "NSE:TNPO-EQ", "NIFTY"/"NIFTY 50", "GIFT NIFTY" etc.
    Fail-closed: (None, reason-chain).
    """
    sym = (symbol or "").strip().upper()
    reasons: list[str] = []

    # ---- Fyers (docs: symbols like "NSE:RELIANCE-EQ" / "NSE:NIFTY50-INDEX")
    fyers_sym = fyers_spot_symbol(sym)
    client, err = await _broker_client(session, user_id, "fyers")
    if client is not None:
        try:
            resp = client.quotes({"symbols": fyers_sym})
            if isinstance(resp, dict) and resp.get("s") == "ok":
                d = (resp.get("d") or [{}])[0]
                v = d.get("v") or {}
                ltp = v.get("lp") or v.get("ltp")
                if ltp:
                    return float(ltp), "fyers"
                reasons.append("fyers: empty LTP")
            else:
                reasons.append(f"fyers: {(resp or {}).get('message', 'error') if isinstance(resp, dict) else 'error'}")
        except Exception as exc:  # noqa: BLE001
            reasons.append(f"fyers: {exc}")
    else:
        reasons.append(err or "fyers unavailable")

    # ---- Groww (docs: get_quote(trading_symbol, exchange, segment); CASH only —
    #      indices are not served on the CASH segment)
    if not is_index_symbol(sym):
        client, err = await _broker_client(session, user_id, "groww")
        if client is not None:
            try:
                resp = client.get_quote(trading_symbol=sym, exchange="NSE", segment="CASH")
                p = resp.get("payload") or resp.get("data") or {}
                ltp = p.get("ltp")
                if ltp:
                    return float(ltp), "groww"
                reasons.append("groww: empty LTP")
            except Exception as exc:  # noqa: BLE001
                reasons.append(f"groww: {exc}")
        else:
            reasons.append(err or "groww unavailable")
    else:
        reasons.append("groww: indices not on CASH segment (using NSE)")

    # ---- Free NSE (works from this server: allIndices + marketStatus)
    px = nse_index_ltp(sym)
    if px is not None:
        return px, "nse"
    reasons.append("nse: not a known index (equity feed needs a working broker token)")

    return None, " · ".join(reasons) or "no quote source"


def _extract_chain_strikes(resp: Any) -> list[dict] | None:
    """Shape-agnostic pull of strike rows out of an option-chain payload.

    Looks for a list of dicts that carry a strike key and CE/PE (or option_type).
    Returns None when nothing recognizable is found (caller falls back to raw).
    """

    def _row(r: dict) -> dict | None:
        strike = r.get("strike") or r.get("strike_price") or r.get("strikePrice") or r.get("strikeprice")
        if strike is None:
            return None
        ce = r.get("CE") or r.get("ce") or r.get("call") or r.get("CALL")
        pe = r.get("PE") or r.get("pe") or r.get("put") or r.get("PUT")
        if isinstance(ce, dict) and isinstance(pe, dict):
            return {
                "strike": strike,
                "CE": {"ltp": ce.get("ltp") or ce.get("last_price") or ce.get("lastPrice"),
                       "oi": ce.get("oi") or ce.get("open_interest") or ce.get("openInterest")},
                "PE": {"ltp": pe.get("ltp") or pe.get("last_price") or pe.get("lastPrice"),
                       "oi": pe.get("oi") or pe.get("open_interest") or pe.get("openInterest")},
            }
        ot = (r.get("option_type") or r.get("optionType") or r.get("type") or "").upper()
        if ot in ("CE", "PE", "CALL", "PUT"):
            return {
                "strike": strike,
                "option_type": "CE" if ot in ("CE", "CALL") else "PE",
                "ltp": r.get("ltp") or r.get("last_price") or r.get("lastPrice"),
                "oi": r.get("oi") or r.get("open_interest") or r.get("openInterest"),
            }
        return None

    def _walk(node: Any, depth: int = 0) -> list[dict] | None:
        if depth > 5:
            return None
        if isinstance(node, list):
            rows = [_row(r) for r in node if isinstance(r, dict)]
            good = [r for r in rows if r is not None]
            if good:
                return good
            return None
        if isinstance(node, dict):
            for key in ("options", "data", "payload", "chain", "records", "filtered", "_expiryData"):
                if key in node:
                    found = _walk(node[key], depth + 1)
                    if found:
                        return found
            for v in node.values():
                if isinstance(v, (dict, list)):
                    found = _walk(v, depth + 1)
                    if found:
                        return found
        return None

    return _walk(resp)


async def get_option_chain(
    session: AsyncSession, user_id: int, symbol: str, expiry: str = ""
) -> dict[str, Any]:
    """Option chain via Groww then Fyers. Returns compact strikes or a raw fallback.

    Groww needs the ₹499 Trading API subscription; Fyers needs a valid token.
    When neither yields a parseable chain, returns the truncated raw payload
    so the LLM can still read it — plus the honest per-source error chain.
    """
    sym = (symbol or "").strip().upper()
    reasons: list[str] = []

    # ---- Groww: get_option_chain(exchange, underlying, expiry_date "YYYY-MM-DD")
    client, err = await _broker_client(session, user_id, "groww")
    if client is not None:
        try:
            resp = client.get_option_chain(exchange="NSE", underlying=sym, expiry_date=expiry or "")
            rows = _extract_chain_strikes(resp)
            if rows:
                return {"via": "groww", "symbol": sym, "expiry": expiry, "strikes": rows[:21]}
            reasons.append("groww: chain shape unrecognized")
            raw_g = json.dumps(resp, default=str)[:1200]
        except Exception as exc:  # noqa: BLE001
            reasons.append(f"groww: {exc}")
            raw_g = ""
    else:
        reasons.append(err or "groww unavailable")
        raw_g = ""

    # ---- Fyers: optionchain({"symbol": "NSE:NIFTY50-INDEX", "strikecount": n, ...})
    client, err = await _broker_client(session, user_id, "fyers")
    if client is not None:
        try:
            data: dict[str, Any] = {
                "symbol": fyers_spot_symbol(sym),
                "strikecount": 11,
                "timestamp": "",
                "greeks": 1,
            }
            resp = client.optionchain(data=data)
            if isinstance(resp, dict) and resp.get("s") == "error":
                reasons.append(f"fyers: {resp.get('message', 'error')}")
            else:
                rows = _extract_chain_strikes(resp)
                if rows:
                    return {"via": "fyers", "symbol": sym, "expiry": expiry, "strikes": rows[:21]}
                reasons.append("fyers: chain shape unrecognized")
                raw_f = json.dumps(resp, default=str)[:1200]
        except Exception as exc:  # noqa: BLE001
            reasons.append(f"fyers: {exc}")
            raw_f = ""
    else:
        reasons.append(err or "fyers unavailable")
        raw_f = ""

    return {
        "error": " · ".join(reasons) or "no chain source",
        "symbol": sym,
        "raw": raw_g or raw_f or "",
        "hint": "Groww option-chain needs the ₹499/mo Trading API subscription; Fyers needs a valid OAuth token.",
    }


async def place_broker_order(
    session: AsyncSession, user_id: int, trade: Trade, rule: Rule
) -> tuple[bool, str]:
    """Live order placement. Untested against real capital — approve-each by default."""
    client, err = await _broker_client(session, user_id, "groww")
    if client is not None:
        try:
            # Docs: segment CASH|FNO; product CNC|Mis|NRML (F&O → NRML); trading_symbol
            # "NIFTY25OCT24000CE" (F&O) / "RELIANCE" (equity); response payload.groww_order_id.
            segment = "CASH" if trade.instrument.startswith("equity") else "FNO"
            t_symbol = groww_contract_symbol(trade.symbol, trade.instrument, trade.expiry, trade.strike)
            resp = client.place_order(
                validity="DAY",
                exchange="NSE",
                order_type="MARKET",
                product=groww_product(trade.instrument),
                quantity=int(trade.qty),
                segment=segment,
                trading_symbol=t_symbol,
                transaction_type=trade.side,
                order_reference_id=trade.id,
            )
            payload = resp.get("payload") or {}
            # Docs response schema: payload.groww_order_id (NOT order_number/order_id)
            order_id = str(
                payload.get("groww_order_id")
                or payload.get("order_number")
                or payload.get("order_id")
                or ""
            )
            if order_id:
                return True, order_id
            return False, str(resp)[:300]
        except Exception as exc:  # noqa: BLE001
            return False, f"groww: {exc}"
    client, err = await _broker_client(session, user_id, "fyers")
    if client is not None:
        try:
            # Docs: symbol must be Fyers format; type 1=market; side ±1; productType
            # CNC (delivery) / INTRADAY; validity DAY; F&O uses the contract symbol.
            data = {
                "symbol": fyers_contract_symbol(trade.symbol, trade.instrument, trade.expiry, trade.strike),
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
