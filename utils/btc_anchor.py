# utils/btc_anchor.py
from __future__ import annotations
import time
import math
from typing import Dict, List, Optional, Tuple

from utils.get_klines import get_klines
from utils.indicators import compute_indicators

# קאש קצר כדי להימנע מספאם לבינאנס
_ANCHOR_CACHE: Dict[Tuple[str, Tuple[str, ...]], Tuple[float, Dict[str, object]]] = {}
_ANCHOR_TTL = 20.0  # שניות

def _clamp(v: float, lo: float, hi: float) -> float:
    try:
        v = float(v)
    except Exception:
        v = lo
    return max(lo, min(hi, v))

def _trend_dir_to_trade_dir(trend: str) -> str:
    t = (trend or "").upper()
    if t == "UP":
        return "LONG"
    if t == "DOWN":
        return "SHORT"
    return "SIDEWAYS"

async def _analyze_tf(symbol: str, tf: str, market: str) -> Optional[Dict[str, float]]:
    df = await get_klines(symbol, interval=tf, limit=180, market_type=market)
    if df is None:
        return None
    df = compute_indicators(df)
    if df is None or df.empty:
        return None
    last = df.iloc[-1]
    trend = str(last.get("trend", "SIDEWAYS")).upper()
    rsi = float(last.get("rsi", 50.0))
    adx = float(last.get("adx", 15.0))
    return {"trend": trend, "rsi": rsi, "adx": adx}

def _combine(frames_stats: List[Dict[str, float]]) -> Tuple[str, int]:
    """
    הופך רשימת {trend, rsi, adx} להחלטת עוגן כוללת: (overall_trend, strength 0..100)
    """
    if not frames_stats:
        return ("SIDEWAYS", 50)
    score = 0.0
    weights_sum = 0.0
    for s in frames_stats:
        tr = (s["trend"] or "SIDEWAYS").upper()
        sign = 1 if tr == "UP" else (-1 if tr == "DOWN" else 0)
        # נרמל ADX (0..1) וסטיית RSI מ-50 (0..1)
        w_adx = _clamp(s["adx"], 0, 50) / 50.0
        w_rsi = _clamp(abs(s["rsi"] - 50.0), 0, 50) / 50.0
        # משקל TF: ADX חזק יותר
        tf_strength = (0.6 * w_adx + 0.4 * w_rsi)  # 0..1
        score += sign * tf_strength
        weights_sum += tf_strength

    if abs(score) < 1e-9:
        return ("SIDEWAYS", 50)

    avg_mag = abs(score) / max(weights_sum, 1e-9)  # 0..1
    overall = "UP" if score > 0 else "DOWN"
    strength = int(round(_clamp(50 + (avg_mag * 50), 0, 100)))
    return (overall, strength)

def _reason(frames: List[str], stats: List[Optional[Dict[str, float]]]) -> str:
    parts = []
    for tf, st in zip(frames, stats):
        if not st:
            parts.append(f"{tf}: no-data")
        else:
            parts.append(f"{tf}: trend={st['trend']} rsi={round(st['rsi'],1)} adx={round(st['adx'],1)}")
    return "; ".join(parts)

async def compute_btc_anchor(frames: List[str], market: str = "futures") -> Dict[str, object]:
    """
    מחשב עוגן BTC עבור רשימת TFs. לעולם לא מעלה חריגה; מחזיר עוגן ניטרלי במקרה תקלה.
    """
    key = (("spot" if str(market).lower() == "spot" else "futures"), tuple(frames or []))
    now = time.time()
    cached = _ANCHOR_CACHE.get(key)
    if cached and (now - cached[0]) <= _ANCHOR_TTL:
        return cached[1]  # type: ignore

    try:
        tfs = [s.strip() for s in (frames or []) if s.strip()]
        if not tfs:
            tfs = ["15m", "1h"]

        stats: List[Optional[Dict[str, float]]] = []
        for tf in tfs:
            st = await _analyze_tf("BTCUSDT", tf, key[0])
            stats.append(st)

        ok_stats = [s for s in stats if s]
        overall_trend, strength = _combine(ok_stats) if ok_stats else ("SIDEWAYS", 50)
        direction = _trend_dir_to_trade_dir(overall_trend)

        out = {
            "symbol": "BTCUSDT",
            "direction": direction,                   # LONG / SHORT / SIDEWAYS
            "trend": overall_trend,                   # UP / DOWN / SIDEWAYS
            "strength": int(strength),                # 0..100
            "frames": tfs,
            "reason": _reason(tfs, stats),
        }
        _ANCHOR_CACHE[key] = (now, out)
        return out
    except Exception as e:
        out = {
            "symbol": "BTCUSDT",
            "direction": "SIDEWAYS",
            "trend": "SIDEWAYS",
            "strength": 50,
            "frames": frames or ["15m", "1h"],
            "reason": f"anchor error: {e}",
        }
        _ANCHOR_CACHE[key] = (now, out)
        return out

def anchor_gate(direction: str, anchor: Dict[str, object], *, strong_th: int = 70, weak_th: int = 55) -> Dict[str, object]:
    """
    קובע האם לבלום/להחליש/לחזק החלטה מול העוגן.
    """
    dir_in = (direction or "SIDEWAYS").upper()
    a_dir = (anchor.get("direction") or "SIDEWAYS").upper()
    strength = int(anchor.get("strength") or 0)

    if a_dir == "SIDEWAYS" or strength < weak_th:
        return {"action": "allow", "reason": "anchor weak/sideways"}

    aligned = (dir_in == "LONG" and a_dir == "LONG") or (dir_in == "SHORT" and a_dir == "SHORT")
    opposite = (dir_in == "LONG" and a_dir == "SHORT") or (dir_in == "SHORT" and a_dir == "LONG")

    if opposite and strength >= strong_th:
        return {"action": "block", "reason": f"BTC {a_dir} strong ({strength})"}
    if opposite:
        return {"action": "downgrade", "penalty": 15, "reason": f"BTC {a_dir} ({strength}) opposes"}
    if aligned and strength >= strong_th:
        return {"action": "boost", "bonus": 12, "reason": f"BTC {a_dir} strong ({strength})"}
    if aligned:
        return {"action": "boost", "bonus": 6, "reason": f"BTC {a_dir} ({strength})"}
    return {"action": "allow", "reason": "anchor neutral"}

def sltp_multipliers(direction: str, anchor: Dict[str, object], *, strong_th: int = 70, weak_th: int = 55) -> Tuple[float, float]:
    """
    מחזיר (sl_mult, tp_mult). ערכי בסיס: 1.0/1.0. מכוונן לפי העוגן.
    """
    dir_in = (direction or "SIDEWAYS").upper()
    a_dir = (anchor.get("direction") or "SIDEWAYS").upper()
    strength = int(anchor.get("strength") or 0)

    if a_dir == "SIDEWAYS" or strength < weak_th:
        return (1.0, 1.0)

    aligned = (dir_in == "LONG" and a_dir == "LONG") or (dir_in == "SHORT" and a_dir == "SHORT")
    opposite = (dir_in == "LONG" and a_dir == "SHORT") or (dir_in == "SHORT" and a_dir == "LONG")

    if aligned and strength >= strong_th:
        return (0.90, 1.20)  # צמצום SL, הרחבת TP
    if aligned:
        return (0.95, 1.10)
    if opposite and strength >= strong_th:
        return (1.20, 0.90)  # הרחבת SL, צמצום TP
    if opposite:
        return (1.10, 0.95)
    return (1.0, 1.0)

