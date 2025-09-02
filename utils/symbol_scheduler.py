# utils/symbol_scheduler.py
from __future__ import annotations
import time, asyncio
from typing import List, Dict, Any
from utils import config as cfg
from utils.http_client import safe_get

FAPI_BASE = cfg.BINANCE_FUTURES_HTTP_BASE

_last_scan: Dict[str, float] = {}  # סימבול -> timestamp

async def fetch_24h_tickers() -> List[Dict[str, Any]]:
    r = await safe_get(f"{FAPI_BASE}/fapi/v1/ticker/24hr")
    return r.json()

def _score_ticker(t: Dict[str, Any]) -> float:
    # ציון לפי נפח ותנודתיות
    try:
        vol = float(t.get("quoteVolume") or 0.0)
        high = float(t.get("highPrice") or 0.0)
        low  = float(t.get("lowPrice") or 0.0)
        last = float(t.get("lastPrice") or 0.0) or 1.0
        rng  = (high - low) / last if last > 0 else 0.0
        return vol * (1.0 + 2.0 * rng)
    except Exception:
        return 0.0

def _cooldown_ok(sym: str, cooldown_sec: int) -> bool:
    ts = _last_scan.get(sym, 0.0)
    return (time.time() - ts) >= cooldown_sec

def mark_scanned(symbols: List[str]) -> None:
    now = time.time()
    for s in symbols:
        _last_scan[s] = now

async def pick_symbols(batch_size: int, *, cooldown_sec: int) -> List[str]:
    # מתוך הרשימת WATCHLIST (אם הוגדרה) או כלל הפיוצ'רס דרך 24hr tickers
    watch = [s.upper() for s in getattr(cfg, "WATCHLIST", [])] or []
    pool: List[str] = []
    try:
        ticks = await fetch_24h_tickers()
        ranked = sorted(ticks, key=_score_ticker, reverse=True)
        for t in ranked:
            sym = str(t.get("symbol") or "").upper()
            # אם יש WATCHLIST – נעדיף אותה; אם לא, ניקח top futures (שלא כוללים perpetual? בבינאנס זה כולל הכול)
            if watch and sym not in watch: 
                continue
            if _cooldown_ok(sym, cooldown_sec):
                pool.append(sym)
            if len(pool) >= 5 * batch_size:  # מאגר מועמדים גדול מספיק
                break
        if not watch:  # אין WATCHLIST → קח top-ranked כללי
            pool = [s for s in pool if s.endswith("USDT")]
    except Exception:
        # fallback: רק watchlist
        pool = [s for s in watch if _cooldown_ok(s, cooldown_sec)]
    return pool[:batch_size]
