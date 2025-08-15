# utils/btc_anchor.py
from __future__ import annotations
from typing import List, Dict, Any, Tuple
import math

from utils.get_klines import get_klines
from utils.indicators import compute_indicators

def _dir_from_trend(trend: str) -> str:
    t = (trend or "").strip().upper()
    if t == "UP": return "LONG"
    if t == "DOWN": return "SHORT"
    return "SIDEWAYS"

def _frame_strength(trend: str, rsi: float, adx: float) -> Tuple[str, int]:
    """הופך נתוני TF לציון 0..100 + כיוון."""
    direction = _dir_from_trend(trend)
    base = 50
    # מומנטום RSI
    if direction == "LONG":
        base += max(0, min(25, int((rsi - 50) * 1.2)))
    elif direction == "SHORT":
        base += max(0, min(25, int((50 - rsi) * 1.2)))
    # כוח מגמה ADX
    base += max(0, min(25, int((adx - 20) * 1.5)))
    return direction, int(max(0, min(100, base)))

async def compute_btc_anchor(frames: List[str], market: str = "futures") -> Dict[str, Any]:
    """מחשב עוגן BTC על בסיס כמה TF-ים."""
    frames = [f.strip() for f in frames if f.strip()]
    out_parts = []
    agg_scores = []
    agg_dirs = []

    for tf in frames:
        df = await get_klines("BTCUSDT", interval=tf, limit=180, market_type=market)
        if df is None or len(df) < 100:
            out_parts.append(f"{tf}: n/a")
            continue
        ind = compute_indicators(df)
        if ind is None or ind.empty:
            out_parts.append(f"{tf}: n/a")
            continue
        last = ind.iloc[-1].to_dict()
        trend = str(last.get("trend", "SIDEWAYS"))
        rsi = float(last.get("rsi", 50.0))
        adx = float(last.get("adx", 20.0))
        direction, strength = _frame_strength(trend, rsi, adx)
        out_parts.append(f"{tf}: trend={trend} rsi={rsi:.1f} adx={adx:.1f}")
        agg_scores.append(strength)
        agg_dirs.append(direction)

    # החלטה כוללת
    dir_final = "SIDEWAYS"
    if agg_dirs:
        ups = sum(1 for d in agg_dirs if d == "LONG")
        downs = sum(1 for d in agg_dirs if d == "SHORT")
        if ups > downs:
            dir_final = "LONG"
        elif downs > ups:
            dir_final = "SHORT"
        else:
            # תיקו: בחר לפי ממוצע משוקלל ADX/RSI (כבר מגולם בציונים)
            dir_final = agg_dirs[-1]  # אחרון קובע

    strength_final = int(round(sum(agg_scores) / len(agg_scores))) if agg_scores else 0
    trend_final = "UP" if dir_final == "LONG" else "DOWN" if dir_final == "SHORT" else "SIDEWAYS"

    return {
        "symbol": "BTCUSDT",
        "direction": dir_final,
        "trend": trend_final,
        "strength": strength_final,
        "frames": frames,
        "reason": "; ".join(out_parts) if out_parts else "",
    }

def anchor_gate(direction: str, anchor: Dict[str, Any], strong_th: int = 70, weak_th: int = 55) -> Dict[str, Any]:
    """קובע פעולה לפי התאמה/סתירה לעוגן."""
    d = (direction or "SIDEWAYS").upper()
    a_dir = str(anchor.get("direction", "SIDEWAYS")).upper()
    a_strength = int(anchor.get("strength", 0))

    if a_dir == "SIDEWAYS" or a_strength < weak_th:
        return {"action": "allow", "reason": "anchor neutral"}

    conflict = (d == "LONG" and a_dir == "SHORT") or (d == "SHORT" and a_dir == "LONG")

    if conflict and a_strength >= strong_th:
        return {"action": "block", "reason": f"conflict with strong BTC {a_dir} ({a_strength})"}
    if conflict:
        return {"action": "downgrade", "reason": f"conflict with BTC {a_dir} ({a_strength})", "penalty": 15}

    # alignment
    if a_strength >= strong_th:
        return {"action": "boost", "reason": f"aligned with strong BTC {a_dir} ({a_strength})", "bonus": 10}
    return {"action": "allow", "reason": "aligned but weak"}

def sltp_multipliers(direction: str, anchor: Dict[str, Any], strong_th: int = 70, weak_th: int = 55) -> Tuple[float, float]:
    gate = anchor_gate(direction, anchor, strong_th=strong_th, weak_th=weak_th)
    act = gate["action"]
    if act == "block":
        return (1.2, 0.9)   # SL רחב יותר, TP שמרני (תואם דוגמאות)
    if act == "downgrade":
        return (1.1, 0.95)
    if act == "boost":
        return (0.9, 1.1)
    return (1.0, 1.0)

