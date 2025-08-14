# utils/symbol_analysis.py
from __future__ import annotations

import logging
from typing import Any, Dict, Optional, List

from utils.indicators import compute_indicators
from utils.quality_score import compute_quality_score
from utils.static_utils import detect_pattern
from utils.get_klines import get_klines
from utils.btc_anchor import anchor_gate  # חדש: לשקלול מול BTC

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

async def analyze_symbol(
    symbol: str,
    market_type: str,
    interval: str,
    limit: int = 100,
    trending_only: bool = False,
    with_ai: bool = False,
    frames: Optional[List[str]] = None,
    btc_anchor: Optional[Dict[str, Any]] = None,  # חדש: עוגן BTC אופציונלי
) -> Optional[Dict[str, Any]]:
    """
    מנתח סימבול ב־TF יחיד ומחזיר פריט עקבי לשימוש בסורק/AI.
    אם סופק btc_anchor — ישוקלל לסיגנל/ביטחון.
    """
    try:
        df = await get_klines(symbol, interval=interval, limit=limit, market_type=market_type)
        if df is None or len(df) < 60:
            logging.warning(f"[*] לא מספיק נרות לניתוח עבור {symbol}@{interval}")
            return None

        df = compute_indicators(df)
        last = df.iloc[-1].to_dict()

        quality = float(compute_quality_score(df) or 0.0)

        trend = _trend_from_indicators(last)  # "UP"/"DOWN"/"SIDEWAYS"
        direction = _norm_direction_from_trend(trend)  # "LONG"/"SHORT"/"SIDEWAYS"

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

        # --- שקלול מול BTC (אם ניתן) ---
        if btc_anchor:
            gate = anchor_gate(direction, btc_anchor)
            if gate["action"] == "block":
                # אל תמליץ — אבל נחזיר פריט עם HOLD כדי שהשכבה הקוראת תוכל להחליט אם להסתיר
                signal = "HOLD"
                confidence = min(confidence, 40)
                reason = f"{reason}; blocked by BTC ({gate['reason']})"
            elif gate["action"] == "downgrade":
                confidence = max(0, confidence - int(gate.get("penalty", 15)))
                reason = f"{reason}; {gate['reason']}"
            elif gate["action"] == "boost":
                confidence = min(100, confidence + int(gate.get("bonus", 10)))
                reason = f"{reason}; {gate['reason']}"

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
