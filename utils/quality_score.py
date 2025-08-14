# utils/quality_score.py
import logging
import numpy as np
import pandas as pd
from typing import Any, Optional

def _f(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return float(default)

def _b(x: Any) -> int:
    """
    ממיר לכללים בינאריים 0/1 (מקבל גם bool/float/str).
    """
    try:
        if isinstance(x, (bool, np.bool_)):
            return int(bool(x))
        if x is None:
            return 0
        # תווים/מספרים
        v = float(x)
        return 1 if v != 0.0 else 0
    except Exception:
        return 0

def _infer_direction(last: dict, prev: Optional[dict] = None) -> str:
    """
    ניסיון להסיק כיוון אם לא הועבר מבחוץ:
    1) supertrend_dir
    2) EMA21 מעל EMA50 -> LONG, אחרת SHORT
    ברירת מחדל: LONG
    """
    try:
        st = last.get("supertrend_dir", None)
        if st is not None:
            return "LONG" if int(st) == 1 else "SHORT"
    except Exception:
        pass
    ema21 = _f(last.get("ema_21"), last.get("close"))
    ema50 = _f(last.get("ema_50"), last.get("close"))
    return "LONG" if ema21 >= ema50 else "SHORT"

def compute_quality_score(
    data: Any,
    direction: Optional[str] = None,
    verbose: bool = False
) -> float:
    """
    מחשב ציון איכות לטרייד (0–10) לפי אינדיקטורים טכניים + בונוסים/קנסות מתבניות נרות.
    תומך ב־DataFrame (לוקח שורה אחרונה) או dict.

    פרמטרים:
      - data: DataFrame או dict של האינדיקטורים.
      - direction: "LONG" / "SHORT" (אופציונלי). אם לא יועבר – ננסה להסיק.
      - verbose: רישום סיבות בלוג.

    החישוב הבסיסי נשאר דומה לגרסה הקודמת, עם התאמות:
      • LONG: +1 כל אחד עבור Bullish Engulfing / Hammer / Morning Star
              -1 כל אחד עבור Bearish Engulfing / Shooting Star / Evening Star
      • SHORT: +1 כל אחד עבור Bearish Engulfing / Shooting Star / Evening Star
               -1 כל אחד עבור Bullish Engulfing / Hammer / Morning Star
      • Doji ניטראלי (0).
    """
    try:
        if isinstance(data, pd.DataFrame) and not data.empty:
            last = data.iloc[-1].to_dict()
            prev = data.iloc[-2].to_dict() if len(data) > 1 else None
        elif isinstance(data, dict):
            last = data
            prev = None
        else:
            logging.warning("[quality_score] סוג נתון לא נתמך")
            return 0.0

        # ------ בסיס (כמו קודם) ------
        score = 0.0
        reasons = []

        # ATR
        atr = _f(last.get("atr"), 0)
        if atr > 0:
            score += 1; reasons.append("ATR תקין")

        # MACD
        macd = _f(last.get("macd"), 0); macd_signal = _f(last.get("macd_signal"), 0)
        if macd > macd_signal:
            score += 1; reasons.append("MACD חיובי")

        # RSI
        rsi = _f(last.get("rsi"), 0)
        if 45 <= rsi <= 65:
            score += 1; reasons.append("RSI נייטרלי")
        # אפשרות לחיזוק קצה (אופציונלי – מתון):
        if rsi >= 65:
            score += 0.5; reasons.append("RSI גבוה (מומנטום)")

        # ADX
        adx = _f(last.get("adx"), 0)
        if adx > 20:
            score += 1; reasons.append("ADX חזק")

        # Volume
        vol = _f(last.get("volume"), 0); vol_mean = max(1e-9, _f(last.get("volume_mean"), 1))
        if vol > vol_mean * 1.5:
            score += 1; reasons.append("נפח גבוה")

        # EMA checks
        close = _f(last.get("close"), 0)
        ema21 = _f(last.get("ema_21"), close)
        ema50 = _f(last.get("ema_50"), close)

        if close > ema21:
            score += 1; reasons.append("מעל EMA21")
        if close > ema50:
            score += 1; reasons.append("מעל EMA50")

        if prev is not None:
            try:
                if _f(last.get("ema_21")) > _f(last.get("ema_50")) and _f(prev.get("ema_21")) <= _f(prev.get("ema_50")):
                    score += 1; reasons.append("חציית EMA21 מעל EMA50")
            except Exception:
                pass

        macd_hist = _f(last.get("macd_hist"), 0)
        if macd_hist > 0:
            score += 1; reasons.append("MACD היסטוגרמה חיובי")

        vwap = _f(last.get("vwap"), close)
        if close > vwap:
            score += 1; reasons.append("מעל VWAP")

        # ------ בונוסים/קנסות לפי תבניות + כיוון ------
        dir_use = (direction or "").strip().upper()
        if dir_use not in ("LONG", "SHORT"):
            dir_use = _infer_direction(last, prev)

        # קריאת הדגלים (0/1)
        bulls_eng = _b(last.get("is_bullish_engulfing"))
        bears_eng = _b(last.get("is_bearish_engulfing"))
        hammer    = _b(last.get("is_hammer"))
        inv_ham   = _b(last.get("is_inverted_hammer"))
        shoot     = _b(last.get("is_shooting_star"))
        morning   = _b(last.get("is_morning_star"))
        evening   = _b(last.get("is_evening_star"))
        doji      = _b(last.get("is_doji"))

        # בונוסים/קנסות
        if dir_use == "LONG":
            if bulls_eng: score += 1; reasons.append("Bullish Engulfing (LONG +1)")
            if hammer:    score += 1; reasons.append("Hammer (LONG +1)")
            if morning:   score += 1; reasons.append("Morning Star (LONG +1)")

            if bears_eng: score -= 1; reasons.append("Bearish Engulfing (LONG -1)")
            if shoot:     score -= 1; reasons.append("Shooting Star (LONG -1)")
            if evening:   score -= 1; reasons.append("Evening Star (LONG -1)")
            # Inverted Hammer לרוב סימן חיובי אחרי ירידה – נשאיר ניטראלי כברירת מחדל
        else:  # SHORT
            if bears_eng: score += 1; reasons.append("Bearish Engulfing (SHORT +1)")
            if shoot:     score += 1; reasons.append("Shooting Star (SHORT +1)")
            if evening:   score += 1; reasons.append("Evening Star (SHORT +1)")

            if bulls_eng: score -= 1; reasons.append("Bullish Engulfing (SHORT -1)")
            if hammer:    score -= 1; reasons.append("Hammer (SHORT -1)")
            if morning:   score -= 1; reasons.append("Morning Star (SHORT -1)")
            # Inverted Hammer – נחשב בדרך כלל bullish reversal, לכן נקנוס מעט:
            if inv_ham:   score -= 0.5; reasons.append("Inverted Hammer (SHORT -0.5)")

        # Doji – ניטראלי (0). אם תרצה – אפשר לשנות ל±0.25 לפי הקשר.

        # סופי: תחום 0–10
        final_score = float(min(max(score, 0.0), 10.0))

        if verbose:
            logging.info(f"[quality_score] ✅ ציון איכות: {final_score} | כיוון: {dir_use} | סיבות: {', '.join(reasons)}")

        return final_score

    except Exception as e:
        logging.error(f"[quality_score] ❌ שגיאה: {e}", exc_info=True)
        return 0.0


def calculate_quality_score(indicators: dict, direction: Optional[str] = None) -> float:
    """
    עטיפה נוחה לשימוש חיצוני.
    """
    return compute_quality_score(indicators, direction=direction, verbose=False)














