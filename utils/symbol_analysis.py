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
    # אם compute_indicators מייצרת "trend" – נשתמש; אחרת, ננסה היגיון פשוט:
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
    with_ai: bool = False,  # נשמר לתאימות; ההחלטה על AI נעשית בשכבה גבוהה יותר
    frames: Optional[List[str]] = None,
) -> Optional[Dict[str, Any]]:
    """
    מנתח סימבול ב־TF יחיד ומחזיר פריט עקבי לשימוש בסורק/AI.
    """
    try:
        df = await get_klines(symbol, interval=interval, limit=limit, market_type=market_type)
        if df is None or len(df) < 60:
            logging.warning(f"[*] לא מספיק נרות לניתוח עבור {symbol}@{interval}")
            return None

        df = compute_indicators(df)
        last = df.iloc[-1].to_dict()

        # איכות כוללת (0..10)
        quality = float(compute_quality_score(df) or 0.0)

        # מגמה -> כיוון מסחר
        trend = _trend_from_indicators(last)  # "UP"/"DOWN"/"SIDEWAYS"
        direction = _norm_direction_from_trend(trend)  # "LONG"/"SHORT"/"SIDEWAYS"

        # תבנית נר
        pattern = detect_pattern(df) or ""

        rsi = float(last.get("rsi", 0.0) or 0.0)
        adx = float(last.get("adx", 0.0) or 0.0)
        vol = float(last.get("volume", 0.0) or 0.0)

        # סיגנל קליל (HOLD אם איכות נמוכה/מגמה צדית)
        signal = "HOLD"
        reason = "low confidence"
        if direction in ("LONG", "SHORT") and trend in ("UP", "DOWN"):
            if quality >= 7:
                signal = "BUY" if direction == "LONG" else "SELL"
                reason = f"trend={trend} quality={quality:.1f}"
            elif quality >= 5:
                signal = "HOLD"
                reason = f"neutral setup, quality={quality:.1f}"

        # ביטוי ביטחון (אחוז) – נגזרת פשוטה מאיכות
        confidence = max(0, min(100, int(round(quality * 10))))

        return {
            "symbol": str(symbol).upper(),
            "market": market_type,
            "frames": frames or [interval],
            "interval": interval,
            "indicators": last,             # נשמרת תמונת אינדיקטורים מלאה
            "trend": trend,                 # "UP"/"DOWN"/"SIDEWAYS"
            "direction": direction,         # "LONG"/"SHORT"/"SIDEWAYS"
            "quality_score": quality,       # 0..10 (float)
            "volume": vol,
            "pattern": pattern,
            "trending": bool(trending_only),
            # שדות ידידותיים לשכבת AI/מסך:
            "rsi": rsi,
            "adx": adx,
            "signal": signal,               # BUY/SELL/HOLD
            "confidence": confidence,       # 0..100
            "reason": reason,
        }

    except Exception as e:
        logging.error(f"[analyze_symbol] שגיאה בניתוח {symbol}@{interval}: {e}", exc_info=True)
        return None
