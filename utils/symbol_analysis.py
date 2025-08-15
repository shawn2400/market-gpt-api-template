# utils/symbol_analysis.py
from __future__ import annotations

import logging
from typing import Any, Dict, Optional, List

from utils.indicators import compute_indicators
from utils.quality_score import compute_quality_score
from utils.static_utils import detect_pattern
from utils.get_klines import get_klines

# שילוב Gate/Boost רשמי מול עוגן BTC
from utils.btc_anchor import anchor_gate

def _norm_direction_from_trend(trend: str) -> str:
    t = (trend or "").strip().lower()
    if t in ("up", "long", "buy", "bull", "bullish"):
        return "LONG"
    if t in ("down", "short", "sell", "bear", "bearish"):
        return "SHORT"
    return "SIDEWAYS"

def _trend_from_indicators(last: Dict[str, Any]) -> str:
    # קודם ננסה עמודת trend אם קיימת (compute_indicators מוסיף "trend")
    tr = str(last.get("trend", "") or "").strip().upper()
    if tr in ("UP", "DOWN", "SIDEWAYS"):
        return tr
    # אם לא – היגיון fallback:
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

def _apply_anchor_effects(
    direction: str,
    quality: float,
    confidence: int,
    btc_anchor: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    מחזיר:
      quality, confidence, anchor_action, anchor_reason, blocked (bool)
    משתמש ב-anchor_gate כדי לסווג block/downgrade/boost/allow.
    """
    if not btc_anchor or not isinstance(btc_anchor, dict):
        return {
            "quality": float(quality),
            "confidence": int(confidence),
            "anchor_action": "none",
            "anchor_reason": "",
            "blocked": False,
        }

    gate = anchor_gate(direction, btc_anchor)
    action = gate.get("action", "allow")
    reason = gate.get("reason", "")

    q = float(quality)
    c = int(confidence)
    blocked = False

    if action == "block":
        # הענשה משמעותית – השכבות למעלה יכולות לזרוק את הפריט לחלוטין
        q = max(0.0, q - 0.9)
        c = max(0, min(c, 35))
        blocked = True
    elif action == "downgrade":
        q = max(0.0, q - 0.4)
        c = max(0, c - int(gate.get("penalty", 15)))
    elif action == "boost":
        q = min(10.0, q + 0.3)
        c = min(100, c + int(gate.get("bonus", 10)))
    # allow → ללא שינוי

    return {
        "quality": float(q),
        "confidence": int(c),
        "anchor_action": str(action),
        "anchor_reason": str(reason),
        "blocked": bool(blocked),
    }

async def analyze_symbol(
    symbol: str,
    market_type: str,
    interval: str,
    limit: int = 100,
    trending_only: bool = False,
    with_ai: bool = False,  # נשמר לתאימות; ההחלטה על AI נעשית בשכבה גבוהה יותר
    frames: Optional[List[str]] = None,
    btc_anchor: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """
    מנתח סימבול ב־TF יחיד ומחזיר פריט עקבי לשימוש בסורק/AI.
    אם מועבר btc_anchor – יבוצעו התאמות איכות/ביטחון ואף סימון "blocked" בעת קונפליקט חזק.
    """
    try:
        df = await get_klines(symbol, interval=interval, limit=limit, market_type=market_type)
        if df is None or len(df) < 60:
            logging.debug(f"[symbol_analysis] לא מספיק נרות לניתוח עבור {symbol}@{interval}")
            return None

        df = compute_indicators(df)
        if df is None or df.empty:
            logging.debug(f"[symbol_analysis] compute_indicators החזיר ריק עבור {symbol}@{interval}")
            return None

        last = df.iloc[-1].to_dict()

        # איכות כוללת (0..10)
        quality = float(compute_quality_score(df) or 0.0)

        # מגמה -> כיוון מסחר
        trend = _trend_from_indicators(last)  # "UP"/"DOWN"/"SIDEWAYS"
        direction = _norm_direction_from_trend(trend)  # "LONG"/"SHORT"/"SIDEWAYS"

        # תבנית נר
        try:
            pattern = detect_pattern(df) or ""
        except Exception:
            pattern = str(last.get("pattern") or "")  # fallback אם detect_pattern איננו

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

        # התאמות לפי עוגן BTC (אם התקבל)
        anchor_action = "none"
        anchor_reason = ""
        blocked = False
        if btc_anchor:
            adj = _apply_anchor_effects(direction, quality, confidence, btc_anchor)
            quality = adj["quality"]
            confidence = adj["confidence"]
            anchor_action = adj["anchor_action"]
            anchor_reason = adj["anchor_reason"]
            blocked = adj["blocked"]

            # אם נחסם – נהפוך ל-HOLD כדי שהשכבות מעל ידעו להשליך
            if blocked:
                signal = "HOLD"
                reason = (reason + "; " if reason else "") + f"blocked by BTC ({anchor_reason})"
            else:
                if anchor_reason:
                    reason = f"{reason}; {anchor_reason}"

        item = {
            "symbol": str(symbol).upper(),
            "market": market_type,
            "frames": frames or [interval],
            "interval": interval,
            "indicators": last,             # תמונת אינדיקטורים מלאה
            "trend": trend,                 # "UP"/"DOWN"/"SIDEWAYS"
            "direction": direction,         # "LONG"/"SHORT"/"SIDEWAYS"
            "quality_score": float(round(quality, 2)),
            "volume": vol,
            "pattern": pattern,
            "trending": bool(trending_only),
            # ידידותי לשכבת AI/תצוגה:
            "rsi": rsi,
            "adx": adx,
            "signal": signal,               # BUY/SELL/HOLD
            "confidence": int(confidence),  # 0..100
            "reason": reason,
        }

        # לצורכי דיאגנוסטיקה – נחזיר גם מטא על העוגן (אם קיים)
        if btc_anchor:
            item["anchor"] = {
                "direction": str(btc_anchor.get("direction", "")),
                "trend": str(btc_anchor.get("trend", "")),
                "strength": int(btc_anchor.get("strength", 0)),
                "frames": list(btc_anchor.get("frames", [])),
                "action": anchor_action,
                "action_reason": anchor_reason,
                "blocked": bool(blocked),
            }

        return item

    except Exception as e:
        logging.error(f"[analyze_symbol] שגיאה בניתוח {symbol}@{interval}: {e}", exc_info=True)
        return None



