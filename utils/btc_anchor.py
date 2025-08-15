# utils/btc_anchor.py
from __future__ import annotations
import logging
from typing import Dict, Any, List, Sequence, Tuple

from utils.scanner_utils import fetch_ohlcv
from utils.indicators import compute_indicators

def _frame_direction_strength(df) -> Tuple[str, float]:
    """
    קובע כיוון (LONG/SHORT/SIDEWAYS) וחוזק 0–100 על סמך EMA21/EMA50 + ADX/RSI.
    """
    if df is None or getattr(df, "empty", True):
        return "SIDEWAYS", 50.0
    dfi = compute_indicators(df)
    if dfi is None or dfi.empty:
        return "SIDEWAYS", 50.0
    last = dfi.iloc[-1]
    try:
        close = float(last.get("close"))
        ema21 = float(last.get("ema_21"))
        ema50 = float(last.get("ema_50"))
    except Exception:
        return "SIDEWAYS", 50.0

    adx = float(last.get("adx", 20.0))
    rsi = float(last.get("rsi", 50.0))

    if ema21 > ema50:
        direction = "LONG"
    elif ema21 < ema50:
        direction = "SHORT"
    else:
        direction = "SIDEWAYS"

    sep_pct = abs(ema21 - ema50) / max(1e-9, close) * 100.0
    strength = 40.0 + min(sep_pct * 5.0, 30.0) + max(0.0, adx - 20.0) * 1.0 + abs(rsi - 50.0) * 0.3
    strength = max(0.0, min(100.0, strength))
    return direction, float(strength)

async def compute_btc_anchor(
    frames: Sequence[str] = ("15m", "1h"),
    market: str = "futures",
) -> Dict[str, Any]:
    """
    מחזיר עוגן BTC: {direction, strength, frames}
    שליפה אסינכרונית דרך fetch_ohlcv (אין await על פונקציה סינכרונית).
    """
    directions: List[str] = []
    strengths: List[float] = []

    for tf in frames or ("15m", "1h"):
        try:
            df = await fetch_ohlcv("BTCUSDT", interval=tf, limit=180, market_type=market)
            d, s = _frame_direction_strength(df)
            directions.append(d)
            strengths.append(s)
        except Exception as e:
            logging.warning(f"[btc_anchor] {tf}: {e}")

    # הכרעת כיוון
    if not directions:
        direction = "SIDEWAYS"
        strength = 50
    else:
        long_cnt = sum(1 for d in directions if d == "LONG")
        short_cnt = sum(1 for d in directions if d == "SHORT")
        if long_cnt > short_cnt:
            direction = "LONG"
        elif short_cnt > long_cnt:
            direction = "SHORT"
        else:
            direction = directions[-1]  # תיקו → מצב אחרון
        strength = int(round(sum(strengths) / max(1, len(strengths))))

    return {"symbol": "BTCUSDT", "frames": list(frames or ("15m", "1h")), "direction": direction, "strength": strength}

def anchor_gate(direction: str, anchor: Dict[str, Any], *, strong_th: int = 70, weak_th: int = 55) -> Dict[str, Any]:
    d = (direction or "").upper()
    a_dir = (anchor or {}).get("direction", "SIDEWAYS")
    a_str = int((anchor or {}).get("strength", 50))

    if a_str >= strong_th:
        if d == a_dir:
            return {"action": "boost", "bonus": 10, "reason": f"aligned strong anchor {a_dir}/{a_str}"}
        else:
            return {"action": "block", "reason": f"opposes strong anchor {a_dir}/{a_str}"}
    if a_str >= weak_th:
        if d == a_dir:
            return {"action": "boost", "bonus": 5, "reason": f"aligned weak anchor {a_dir}/{a_str}"}
        else:
            return {"action": "downgrade", "penalty": 10, "reason": f"opposes weak anchor {a_dir}/{a_str}"}
    return {"action": "neutral", "reason": f"anchor weak {a_dir}/{a_str}"}

def sltp_multipliers(direction: str, anchor: Dict[str, Any], *, strong_th: int = 70, weak_th: int = 55) -> Tuple[float, float]:
    """
    מחזיר (sl_mult, tp_mult): מכפיל למרחקי SL/TP.
    """
    d = (direction or "").upper()
    a_dir = (anchor or {}).get("direction", "SIDEWAYS")
    a_str = int((anchor or {}).get("strength", 50))

    if a_str >= strong_th:
        if d == a_dir:
            return (0.90, 1.10)  # SL קרוב יותר, TP רחוק יותר
        else:
            return (1.10, 0.90)  # SL רחוק יותר, TP קרוב יותר
    if a_str >= weak_th:
        if d == a_dir:
            return (0.95, 1.05)
        else:
            return (1.05, 0.95)
    return (1.00, 1.00)


