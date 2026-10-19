"""Fyers symbol master: authoritative, daily-refreshed instrument list.

Per Fyers docs the master files are the only reliable way to map a name to an
exact symbol ("don't guess — look it up"). Used to turn an invalid ticker like
"TNPO" into a helpful "did you mean TNPETRO?" instead of a bare -300 error.

Masters (refreshed every trading day):
  NSE_CM  NSE Capital Market (equities + indices)
  BSE_CM  BSE Capital Market
JSON: https://public.fyers.in/sym_details/{master}_sym_master.json
"""
from __future__ import annotations

import gzip
import json
import logging
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from app.config import DATA_DIR

log = logging.getLogger("igris.fyers_symbols")

BASE_URL = "https://public.fyers.in/sym_details/{}_sym_master.json"
CACHE_DIR = Path(DATA_DIR) / "fyers_sym"
MASTERS = ("NSE_CM", "BSE_CM")
_UA = {"User-Agent": "Mozilla/5.0 (Igris)"}
_TIMEOUT = 25


def _cache_path(master: str) -> Path:
    return CACHE_DIR / f"{master}.json"


def _fresh(path: Path) -> bool:
    """Cache counts as fresh only if written today (masters refresh daily)."""
    if not path.exists():
        return False
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).date() == datetime.now(timezone.utc).date()


def load_master(master: str) -> dict:
    """Return {symbol_ticker: record}, downloading/caching the master for today."""
    if master not in MASTERS:
        return {}
    path = _cache_path(master)
    if not _fresh(path):
        try:
            req = urllib.request.Request(BASE_URL.format(master), headers=_UA)
            raw = urllib.request.urlopen(req, timeout=_TIMEOUT).read()
            if raw[:2] == b"\x1f\x8b":
                raw = gzip.decompress(raw)
            data = json.loads(raw)
            if not isinstance(data, dict) or not data:
                raise ValueError("empty master payload")
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data))
        except Exception as exc:  # noqa: BLE001 — never let lookups break quote paths
            log.debug("symbol master %s refresh failed: %s", master, exc)
            if path.exists():
                try:
                    return json.loads(path.read_text())
                except (OSError, ValueError):
                    pass
            return {}
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def search(term: str, limit: int = 5) -> list[dict]:
    """Case-insensitive match on ticker or company/index name across NSE + BSE."""
    q = (term or "").strip().upper()
    if not q:
        return []
    out: list[dict] = []
    for master in MASTERS:
        for sym, v in load_master(master).items():
            if not isinstance(v, dict):
                continue
            hay = f"{sym} {v.get('exSymName', '')} {v.get('symDetails', '')}".upper()
            if q not in hay:
                continue
            out.append({
                "symbol": v.get("symTicker") or sym,
                "name": v.get("exSymName") or v.get("symDetails") or "",
            })
            if len(out) >= limit:
                return out
    return out


def suggest(ticker: str, limit: int = 3) -> list[str]:
    """'Did you mean' list for an unknown bare ticker.

    Substring search alone is misleading (query "TNPO" substring-matches
    "RTNPOWER" but not the real target "TNPETRO"), so ranking uses difflib
    similarity over tickers that share the first character (a cheap prefilter
    that also drops most false positives), then falls back to substring hits.
    """
    base = (ticker or "").strip().upper()
    if ":" in base:
        base = base.split(":")[-1].removesuffix("-EQ").removesuffix("-INDEX").strip()
    if not base or len(base) < 2:
        return []

    import difflib

    ranked: list[tuple[float, str]] = []
    substring: list[str] = []
    seen: set[str] = set()
    first = base[0]
    for master in MASTERS:
        for sym, v in load_master(master).items():
            if not isinstance(v, dict):
                continue
            short = sym.split(":")[-1]
            for suffix in ("-EQ", "-BE", "-INDEX", "-A", "-B"):
                short = short.removesuffix(suffix)
            short = short.strip()
            if not short or short in seen:
                continue
            seen.add(short)
            if short[0] != first:
                continue  # same-first-letter prefilter
            score = difflib.SequenceMatcher(None, base, short).ratio()
            if score >= 0.62:
                ranked.append((score, short))
            elif len(base) >= 3 and base in short and short not in substring:
                substring.append(short)

    ranked.sort(key=lambda x: (-x[0], x[1]))
    out = [s for _, s in ranked[:limit]]
    if len(out) < limit:
        out += [s for s in substring if s not in out][: limit - len(out)]
    return out
