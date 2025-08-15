# utils/btc_anchor.py
from __future__ import annotations
import os, time
from typing import List, Dict, Any, Optional, Tuple

# תאימות: קודם ננסה get_klines מהמודול שהגדרת, ואם לא – מהחלופי
try:
    from utils.get_klines import get_klines  # type: ignore
except Exception:
    from utils.klines import get_klines  # type: ignore

from utils.indicators import compute_indicators

# קאש קצר לעוגן כדי לא להעמיס (שניות)
_ANCHOR_TTL = int(os.getenv("BTC_ANCHOR_TTL", "20"))
# ספי פעולה
_STRONG_TH = int(os.getenv("BTC_ANCHOR_STRONG_TH", "70"))
_WEAK_TH   = int(os.getenv("BTC_ANCHOR_WEAK_TH",   "55"))

# (market, frames_key) -> (expire_ts, data)
_ANCHOR_CACHE: Dict[Tuple[str, str], Tuple[float, Dict[str, Any]]] = {}


def _trend_from_indicators(last: Dict[str, Any]) -> str:
    ema21 = float(last.get("ema_21", 0.0) or 0.0)
    ema50 = float(last.get("ema_50", 0.0) or 0.0)
    close = float(last.get("close", 0.0) or 0.0)
    tr = str(last.get("trend") or "").upper()
    if tr in ("UP", "DOWN", "SIDEWAYS"):
        return tr
    if close <= 0:
        return "SIDEWAYS"
    if ema21 > ema50 and close > ema21:
        return "UP"
    if ema21 < ema50 and close < ema21:
        return "DOWN"
    return "SIDEWAYS"


async def compute_btc_anchor(frames: List[str] | None = None, market: str = "futures") -> Dict[str, Any]:
    """
    מחשב את מצב ה-BTC (כיוון/מגמה/חוזק) על פני כמה TF-ים, עם קאש קצר.
    """
    frames = frames or ["15m", "1h"]
    key = (market, ",".join(frames))
    now = time.time()

    cached = _ANCHOR_CACHE.get(key)
    if cached and cached[0] > now:
        return cached[1]

    dir_scores: List[int] = []
    strengths: List[int] = []
    reasons: List[str] = []

    for tf in frames:
        df = await get_klines("BTCUSDT", interval=tf, limit=150, market_type=market)
        if df is None or len(df) < 60:
            continue
        df = compute_indicators(df)
        last = df.iloc[-1].to_dict()

        trend = _trend_from_indicators(last)
        direction = "LONG" if trend == "UP" else ("SHORT" if trend == "DOWN" else "SIDEWAYS")
        adx = float(last.get("adx", 0.0) or 0.0)
        rsi = float(last.get("rsi", 50.0) or 50.0)

        score = 1 if direction == "LONG" else (-1 if direction == "SHORT" else 0)
        dir_scores.append(score)

        # חוזק פשוט: ADX + התאמת RSI לכיוון
        s = 40
        if adx >= 25: s += 20
        if direction == "LONG" and rsi >= 55: s += 20
        if direction == "SHORT" and rsi <= 45: s += 20
        s = max(0, min(100, s))
        strengths.append(int(s))

        reasons.append(f"{tf}: trend={trend} rsi={rsi:.1f} adx={adx:.1f}")

    if not dir_scores:
        anchor = {"symbol": "BTCUSDT", "direction": "SIDEWAYS", "trend": "SIDEWAYS",
                  "strength": 0, "frames": frames, "reason": "no data"}
    else:
        agg = sum(dir_scores)
        if agg > 0:
            dir_final, trend = "LONG", "UP"
        elif agg < 0:
            dir_final, trend = "SHORT", "DOWN"
        else:
            dir_final, trend = "SIDEWAYS", "SIDEWAYS"
        strength = int(round(sum(strengths) / len(strengths))) if strengths else 0
        anchor = {"symbol": "BTCUSDT", "direction": dir_final, "trend": trend,
                  "strength": strength, "frames": frames, "reason": "; ".join(reasons)}

    _ANCHOR_CACHE[key] = (now + _ANCHOR_TTL, anchor)
    return anchor


def anchor_gate(alt_direction: str, anchor: Dict[str, Any],
                strong_th: int = _STRONG_TH, weak_th: int = _WEAK_TH) -> Dict[str, Any]:
    """
    קובע Gate לפוזיציית אלט אל מול העוגן:
      - block (נגד BTC חזק)
      - downgrade (נגד BTC בינוני)
      - boost (עם BTC בינוני+)
      - allow (ניטרלי)
    """
    adir = (alt_direction or "SIDEWAYS").upper()
    adir = "LONG" if adir in ("LONG", "BUY") else ("SHORT" if adir in ("SHORT", "SELL") else "SIDEWAYS")
    a_dir = (anchor.get("direction") or "SIDEWAYS").upper()
    s = int(anchor.get("strength") or 0)

    conflict = (adir == "LONG" and a_dir == "SHORT") or (adir == "SHORT" and a_dir == "LONG")

    if conflict and s >= strong_th:
        return {"action": "block", "penalty": 25, "reason": f"conflict with BTC {a_dir} (strength {s})"}
    if conflict and s >= weak_th:
        return {"action": "downgrade", "penalty": 15, "reason": f"weak conflict with BTC {a_dir} (strength {s})"}
    if adir != "SIDEWAYS" and a_dir == adir and s >= weak_th:
        return {"action": "boost", "bonus": 10, "reason": f"aligned with BTC {a_dir} (strength {s})"}
    return {"action": "allow", "reason": "neutral"}


def sltp_multipliers(alt_direction: str, anchor: Dict[str, Any],
                     strong_th: int = _STRONG_TH, weak_th: int = _WEAK_TH) -> Tuple[float, float]:
    """
    מחזיר (SL_mult, TP_mult) לכוונון מרחקי SL/TP לפי העוגן.
    """
    adir = (alt_direction or "SIDEWAYS").upper()
    adir = "LONG" if adir in ("LONG", "BUY") else ("SHORT" if adir in ("SHORT", "SELL") else "SIDEWAYS")
    a_dir = (anchor.get("direction") or "SIDEWAYS").upper()
    s = int(anchor.get("strength") or 0)

    conflict = (adir == "LONG" and a_dir == "SHORT") or (adir == "SHORT" and a_dir == "LONG")

    if conflict and s >= strong_th:
        return 1.20, 0.80  # מרחיבים SL, מצמצמים TP
    if conflict and s >= weak_th:
        return 1.10, 0.90
    if adir != "SIDEWAYS" and a_dir == adir:
        if s >= strong_th:
            return 0.90, 1.20  # מצמצמים SL, מרחיבים TP
        if s >= weak_th:
            return 0.95, 1.10
    return 1.00, 1.00

