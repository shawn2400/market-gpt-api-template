# utils/derivatives_metrics.py
from __future__ import annotations
import os, math
from typing import Dict, Any, List, Optional
import httpx

_FAPI = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com").rstrip("/")

def _client(timeout: float = 6.0) -> httpx.Client:
    return httpx.Client(timeout=timeout)

def _safe_float(x) -> float:
    try: return float(x)
    except Exception: return math.nan

def long_short_ratio(symbol: str, period: str = "5m", limit: int = 30, source: str = "global") -> Dict[str, Any]:
    """
    source in: global | topAccounts | topPositions
    """
    symbol = (symbol or "").upper().strip()
    src = str(source).lower()
    if src == "global":
        ep = f"{_FAPI}/futures/data/globalLongShortAccountRatio"
    elif src == "topaccounts":
        ep = f"{_FAPI}/futures/data/topLongShortAccountRatio"
    elif src == "toppositions":
        ep = f"{_FAPI}/futures/data/topLongShortPositionRatio"
    else:
        ep = f"{_FAPI}/futures/data/globalLongShortAccountRatio"

    params = {"symbol": symbol, "period": period, "limit": max(1, min(500, int(limit)))}
    with _client() as c:
        r = c.get(ep, params=params)
        r.raise_for_status()
        data = r.json()

    # Normalize last point
    last = data[-1] if data else {}
    ratio = _safe_float(last.get("longShortRatio"))
    return {"ok": True, "symbol": symbol, "period": period, "limit": params["limit"], "series": data, "last_ratio": ratio}

def taker_delta_volume(symbol: str, period: str = "5m", limit: int = 30) -> Dict[str, Any]:
    """
    מבוסס על /futures/data/takerlongshortRatio – מחזיר buy/sell volumes ו־delta.
    """
    symbol = (symbol or "").upper().strip()
    ep = f"{_FAPI}/futures/data/takerlongshortRatio"
    params = {"symbol": symbol, "period": period, "limit": max(1, min(500, int(limit)))}
    with _client() as c:
        r = c.get(ep, params=params)
        r.raise_for_status()
        data = r.json()

    # ה־API מחזיר buyVol, sellVol, buySellRatio לכל נקודה
    last = data[-1] if data else {}
    buy_vol = _safe_float(last.get("buyVol"))
    sell_vol = _safe_float(last.get("sellVol"))
    delta = (buy_vol - sell_vol) if not (math.isnan(buy_vol) or math.isnan(sell_vol)) else math.nan
    share = (buy_vol / (buy_vol + sell_vol)) if (buy_vol + sell_vol) > 0 else math.nan

    return {
        "ok": True, "symbol": symbol, "period": period, "limit": params["limit"],
        "series": data,
        "last": {"buy_vol": buy_vol, "sell_vol": sell_vol, "delta": delta, "buy_share": share}
    }

def funding_heatmap(symbols: List[str], limit: int = 24) -> Dict[str, Any]:
    """
    מחזיר היסטוריית funding לכל סימבול ומחשב מגמת שינוי.
    """
    out: Dict[str, Any] = {"ok": True, "limit": max(1, min(1000, int(limit))), "items": []}
    with _client() as c:
        for sym in [s.upper().strip() for s in symbols if s.strip()]:
            r = c.get(f"{_FAPI}/fapi/v1/fundingRate", params={"symbol": sym, "limit": out["limit"]})
            r.raise_for_status()
            lst = r.json()
            rates = [ _safe_float(it.get("fundingRate")) for it in lst ]
            trend = None
            if len(rates) >= 2 and not any(math.isnan(x) for x in rates[-2:]):
                trend = "↑" if rates[-1] > rates[-2] else ("↓" if rates[-1] < rates[-2] else "→")
            out["items"].append({"symbol": sym, "series": lst, "last_rate": rates[-1] if rates else None, "trend": trend})
    return out
