# utils/symbol_analysis.py
from __future__ import annotations

import logging
from typing import Any, Dict, Optional, List

from utils.indicators import compute_indicators
from utils.quality_score import compute_quality_score
from utils.static_utils import detect_pattern
from utils.get_klines import get_klines

def _norm_direction_from_trend(trend: str) -> str:
    t = (trend or "").strip().lower()
    if t in ("up", "long", "buy", "bull", "bullish"):
        return "LONG"
    if t in ("down", "short", "sell", "bear", "bearish"):
        return "SHORT"
    return "SIDEWAYS"

def _trend_from_indicators(last: Dict[str, Any]) -> str:
    tr = str(last.get("trend", "") or "").strip().upper()
    if tr:
        return tr
    ema21 = float(last.get("ema_21", 0.0) or 0.0)
    ema50 = float(last.get("ema_50", 0.0) or 0.0)
    close = float(last.get("close", 0.0) or 0.0)
    if close <= 0:
        return "SIDEWAYS"
    if ema21 > ema50 and close > ema21:
        return "UP"
    if ema21 < ema50 and close < ema21:
        return "DOWN"
    return "SIDEWAYS"

def _apply_anchor_adjustments(
    direction: str,
    quality: float,
    confidence: int,
    anchor: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    if not anchor or not isinstance(anchor, dict):
        return {"quality": quality, "confidence": confidence, "anchor_note": None, "blocked": False}

    a_dir = str(anchor.get("direction") or "SIDEWAYS").upper()
    a_str = float(anchor.get("strength") or 0.0)
    note = f"anchor={a_dir}/{a_str:.0f}"

    aligned = (direction == "LONG" and a_dir == "UP") or (direction == "SHORT" and a_dir == "DOWN")

    q = float(quality)
    c = int(confidence)

    if a_dir in ("UP", "DOWN"):
        if a_str >= 70:
            if aligned:
                q += 0.5; c = min(100, c + 10)
            else:
                q -= 0.7; c = max(0, c - 15)
        elif a_str >= 55:
            if aligned:
                q += 0.3; c = min(100, c + 6)
            else:
                q -= 0.4; c = max(0, c - 8)

    return {"quality": max(0.0, min(10.0, q)), "confidence": c, "anchor_note": note, "blocked": False}

async def analyze_symbol(
    symbol: str,
    market_type: str,
    interval: str,
    limit: int = 100,
    trending_only: bool = False,
    with_ai: bool = False,
    frames: Optional[List[str]] = None,
    btc_anchor: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    try:
        df = await get_klines(symbol, interval=interval, limit=limit, market_type=market_type)
        if df is None or len(df) < 60:
            logging.warning(f"[*] לא מספיק נרות לניתוח עבור {symbol}@{interval}")
            return None

        df = compute_indicators(df)
        last = df.iloc[-1].to_dict()

        quality = float(compute_quality_score(df) or 0.0)

        trend = _trend_from_indicators(last)
        direction = _norm_direction_from_trend(trend)

        pattern = detect_pattern(df) or ""

        rsi = float(last.get("rsi", 0.0) or 0.0)
        adx = float(last.get("adx", 0.0) or 0.0)
        vol = float(last.get("volume", 0.0) or 0.0)

        signal = "HOLD"
        reason = "low confidence"
        if direction in ("LONG", "SHORT") and trend in ("UP", "DOWN"):
            if quality >= 7:
                signal = "BUY" if direction == "LONG" else "SELL"
                reason = f"trend={trend} quality={quality:.1f}"
            elif quality >= 5:
                signal = "HOLD"
                reason = f"neutral setup, quality={quality:.1f}"

        confidence = max(0, min(100, int(round(quality * 10))))

        adj = _apply_anchor_adjustments(direction, quality, confidence, btc_anchor)
        quality = adj["quality"]
        confidence = adj["confidence"]
        if adj.get("anchor_note"):
            reason = f"{reason}; {adj['anchor_note']}"

        return {
            "symbol": str(symbol).upper(),
            "market": market_type,
            "frames": frames or [interval],
            "interval": interval,
            "indicators": last,
            "trend": trend,
            "direction": direction,
            "quality_score": quality,
            "volume": vol,
            "pattern": pattern,
            "trending": bool(trending_only),
            "rsi": rsi,
            "adx": adx,
            "signal": signal,
            "confidence": confidence,
            "reason": reason,
        }
    except Exception as e:
        logging.error(f"[analyze_symbol] שגיאה בניתוח {symbol}@{interval}: {e}", exc_info=True)
        return None


