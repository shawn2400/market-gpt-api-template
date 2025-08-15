# utils/btc_anchor.py
from __future__ import annotations
import math
from typing import List, Dict, Any, Optional, Tuple

import pandas as pd

from utils.get_klines import aget_klines   # ✅ עטיפה אסינכרונית
from utils.indicators import compute_indicators

def _norm_dir(v: Any) -> Optional[str]:
    s = str(v or "").strip().upper()
    if s in ("LONG", "BUY", "UP", "BULL", "BULLISH"):
        return "LONG"
    if s in ("SHORT", "SELL", "DOWN", "BEAR", "BEARISH"):
        return "SHORT"
    return None

def _ema_slope_strength(ema_fast: float, ema_slow: float, close: float) -> float:
    """
    אומדן חוזק פשוט: פער EMA ביחס למחיר (באחוזים) מומר ל-0..100.
    """
    try:
        gap = abs(float(ema_fast) - float(ema_slow))
        if close <= 0:
            return 0.0
        pct = (gap / float(close)) * 100.0
        # map: 0%->0, 0.5%->50, 1.0%->80, 2%->100 (קאפ)
        if pct >= 2.0:
            return 100.0
        if pct >= 1.0:
            return 80.0 + (pct - 1.0) * 20.0
        return min(80.0, pct * 100.0)  # 0..80
    except Exception:
        return 0.0

async def _anchor_for_tf(tf: str, market: str) -> Optional[Dict[str, Any]]:
    """
    מחשב עוגן ל-TF בודד לפי EMA21/50 וחוזק.
    """
    df = await aget_klines("BTCUSDT", interval=tf, limit=180, market_type=market)
    if df is None or df.empty:
        return None
    dfi = compute_indicators(df)
    if dfi is None or dfi.empty:
        return None
    last = dfi.iloc[-1]
    close = float(last.get("close", 0.0) or 0.0)
    ema21 = float(last.get("ema_21", 0.0) or 0.0)
    ema50 = float(last.get("ema_50", 0.0) or 0.0)

    direction = "LONG" if ema21 > ema50 else "SHORT" if ema21 < ema50 else None
    if direction is None:
        return None

    strength = _ema_slope_strength(ema21, ema50, close)

    # אם יש ADX מהאינדיקטורים שלך – נשקלל קלות (לא חובה)
    try:
        adx = float(last.get("adx", 0.0) or 0.0)
        # קליפ 10..40 → 0..+10 חיזוק
        if adx > 10:
            bonus = min(10.0, (adx - 10.0) * 0.33)
            strength = min(100.0, strength + bonus)
    except Exception:
        pass

    return {
        "tf": tf,
        "direction": direction,
        "strength": round(float(strength), 2),
        "close": close,
        "ema_21": ema21,
        "ema_50": ema50,
    }

async def compute_btc_anchor(*, frames: List[str] | Tuple[str, ...] = ("15m", "1h"), market: str = "futures") -> Dict[str, Any]:
    """
    מחשב עוגן BTC מצרפי על פני כמה TFs: כיוון רוב, חוזק ממוצע.
    החזרה:
      {
        direction: LONG/SHORT,
        strength: 0..100,
        trend: "UP"/"DOWN",
        frames: [...],
        details: [{tf, direction, strength, ...}, ...]
      }
    """
    fr = [str(x).strip() for x in (frames or ("15m", "1h")) if str(x).strip()]
    details: List[Dict[str, Any]] = []
    for tf in fr:
        try:
            item = await _anchor_for_tf(tf, market)
            if item:
                details.append(item)
        except Exception:
            continue

    if not details:
        return {"direction": "LONG", "strength": 50, "trend": "UP", "frames": fr, "details": []}

    longs = sum(1 for d in details if d.get("direction") == "LONG")
    shorts = sum(1 for d in details if d.get("direction") == "SHORT")
    direction = "LONG" if longs >= shorts else "SHORT"

    strength = sum(float(d.get("strength", 0.0)) for d in details) / max(1, len(details))
    trend = "UP" if direction == "LONG" else "DOWN"

    return {
        "direction": direction,
        "strength": round(float(strength), 2),
        "trend": trend,
        "frames": fr,
        "details": details,
    }

def anchor_gate(direction: Optional[str], anchor: Optional[Dict[str, Any]], *, strong_th: int = 70, weak_th: int = 55) -> Dict[str, Any]:
    """
    מחזיר פעולה לפי התאמה לעוגן:
      - align & strong  → boost
      - align & weak    → none
      - oppose & strong → block
      - oppose & weak   → downgrade
    """
    d = _norm_dir(direction)
    if not anchor or not isinstance(anchor, dict):
        return {"action": "none", "reason": "no anchor"}

    a_dir = _norm_dir(anchor.get("direction"))
    strength = float(anchor.get("strength", 0.0) or 0.0)
    if not d or not a_dir:
        return {"action": "none", "reason": "indeterminate"}

    if d == a_dir:
        if strength >= strong_th:
            return {"action": "boost", "bonus": 12, "reason": f"aligned with BTC ({a_dir}, {strength})"}
        return {"action": "none", "reason": f"aligned (weak, {strength})"}

    # נגד הכיוון
    if strength >= strong_th:
        return {"action": "block", "reason": f"against BTC ({a_dir}, {strength})"}
    return {"action": "downgrade", "penalty": 15, "reason": f"against (weak, {strength})"}

def sltp_multipliers(direction: str, anchor: Optional[Dict[str, Any]], *, strong_th: int = 70, weak_th: int = 55) -> Tuple[float, float]:
    """
    מכפילים ל-SL/TP לפי התאמה לעוגן:
      חיזוק עם העוגן → TP↑, SL↓ ; נגד העוגן → TP↓, SL↑.
    מחזיר: (sl_mult, tp_mult)
    """
    d = _norm_dir(direction)
    if not anchor or not d:
        return (1.0, 1.0)

    a_dir = _norm_dir(anchor.get("direction"))
    strength = float(anchor.get("strength", 0.0) or 0.0)

    if a_dir == d:
        if strength >= strong_th:
            return (0.90, 1.15)  # SL קטן יותר, TP גדול יותר
        if strength >= weak_th:
            return (1.00, 1.08)
        return (1.00, 1.02)
    else:
        if strength >= strong_th:
            return (1.25, 0.85)
        if strength >= weak_th:
            return (1.10, 0.95)
        return (1.05, 0.98)



