# utils/dynamic_filters.py
"""
Dynamic Filter Adjustment System
מתאים את סינוני האיכות בזמן אמת לפי תנאי השוק
"""
from __future__ import annotations
import os
from typing import Dict, Any, Optional

# ====== Base thresholds (VERY Aggressive - GET TRADES NOW!) ======
BASE_SUCCESS_PCT = 50.0  # נמוך מאוד!
BASE_RR_TOP10 = 1.05     # נמוך מאוד!
BASE_RR_ALT = 1.1        # נמוך מאוד!
BASE_QUALITY = 5.0       # נמוך מאוד!

# ====== Adjustment ranges ======
SUCCESS_MIN = 40.0       # מינימום מאוד נמוך
SUCCESS_MAX = 60.0       # מקסימום נמוך
RR_TOP10_MIN = 1.01      # מינימום מינימלי!
RR_TOP10_MAX = 1.3       # מקסימום נמוך
RR_ALT_MIN = 1.05        # מינימום מינימלי!
RR_ALT_MAX = 1.4         # מקסימום נמוך
QUALITY_MIN = 4.0        # מינימום מאוד נמוך
QUALITY_MAX = 6.5        # מקסימום נמוך

# ====== Market regime weights ======
REGIME_WEIGHTS = {
    "TREND": 0.3,      # טרנד חזק = הרחב סינונים
    "BREAKOUT": 0.25,  # ברייקאאוט = הרחב
    "MEAN_REVERT": -0.2,  # מיקוד טווח = החמר
    "CHOP": -0.3,      # צ'ופ = החמר מאוד
}

VOL_REGIME_WEIGHTS = {
    "high": 0.2,    # ווליום גבוה = הרחב
    "mid": 0.0,     # ווליום בינוני = נייטרלי
    "low": -0.25,   # ווליום נמוך = החמר
}


def _clamp(val: float, min_val: float, max_val: float) -> float:
    """גבול ערך לטווח"""
    return max(min_val, min(max_val, val))


def calculate_market_score(ctx: Dict[str, Any]) -> float:
    """
    מחשב ציון שוק כללי (-1 = רע מאוד, +1 = מצוין).
    מבוסס על:
    - Regime (TREND/CHOP/etc)
    - Volume regime
    - ADX (כוח טרנד)
    - ATR% (תנודתיות)
    """
    score = 0.0
    
    # 1. Regime
    regime = (ctx.get("filters") or {}).get("regime", "")
    score += REGIME_WEIGHTS.get(regime, 0.0)
    
    # 2. Volume regime
    vol_regime = (ctx.get("filters") or {}).get("vol_regime", "mid")
    score += VOL_REGIME_WEIGHTS.get(vol_regime, 0.0)
    
    # 3. ADX (כוח טרנד)
    adx = float((ctx.get("filters") or {}).get("adx") or 0)
    if adx >= 30:
        score += 0.25  # טרנד מאוד חזק
    elif adx >= 22:
        score += 0.15  # טרנד בינוני
    elif adx < 15:
        score -= 0.2   # חלש/צ'ופ
    
    # 4. ATR% (תנודתיות)
    atr_pct = float((ctx.get("filters") or {}).get("atr_pct") or 0)
    if atr_pct > 2.5:
        score -= 0.15  # תנודתיות גבוהה מדי = מסוכן
    elif atr_pct < 0.5:
        score -= 0.1   # תנודתיות נמוכה מדי = קשה להרוויח
    
    # 5. BTC Anchor (אם זה BTC עצמו)
    if ctx.get("symbol", "").upper() == "BTCUSDT":
        score += 0.1  # BTC תמיד יותר אמין
    
    return _clamp(score, -1.0, 1.0)


def get_dynamic_thresholds(
    symbol: str,
    ctx: Optional[Dict[str, Any]] = None,
    market_score: Optional[float] = None,
) -> Dict[str, float]:
    """
    מחזיר סינונים דינמיים לפי תנאי השוק.
    
    market_score:
    - +1.0 = שוק מצוין → סינונים מורחבים (Aggressive)
    -  0.0 = שוק בינוני → סינונים בסיסיים (Balanced)
    - -1.0 = שוק גרוע → סינונים מחמירים (Conservative)
    """
    # חשב market score אם לא סופק
    if market_score is None and ctx:
        market_score = calculate_market_score(ctx)
    elif market_score is None:
        market_score = 0.0
    
    # התאם סינונים על סמך ציון השוק
    # ציון חיובי = הקל על הסינונים (יותר הצעות)
    # ציון שלילי = החמר על הסינונים (פחות הצעות, איכות גבוהה)
    
    adjustment = market_score  # -1.0 to +1.0
    
    # Success % - ככל שהשוק טוב יותר, נדרוש פחות
    success_range = SUCCESS_MAX - SUCCESS_MIN
    success_pct = BASE_SUCCESS_PCT - (adjustment * (success_range / 2))
    success_pct = _clamp(success_pct, SUCCESS_MIN, SUCCESS_MAX)
    
    # RR - ככל שהשוק טוב יותר, נדרוש פחות
    rr_top10_range = RR_TOP10_MAX - RR_TOP10_MIN
    rr_top10 = BASE_RR_TOP10 - (adjustment * (rr_top10_range / 2))
    rr_top10 = _clamp(rr_top10, RR_TOP10_MIN, RR_TOP10_MAX)
    
    rr_alt_range = RR_ALT_MAX - RR_ALT_MIN
    rr_alt = BASE_RR_ALT - (adjustment * (rr_alt_range / 2))
    rr_alt = _clamp(rr_alt, RR_ALT_MIN, RR_ALT_MAX)
    
    # Quality Score - ככל שהשוק טוב יותר, נדרוש פחות
    quality_range = QUALITY_MAX - QUALITY_MIN
    quality = BASE_QUALITY - (adjustment * (quality_range / 2))
    quality = _clamp(quality, QUALITY_MIN, QUALITY_MAX)
    
    # Check for ENV overrides (למי שרוצה לכפות ערכים ידנית)
    return {
        "success_pct_min": float(os.getenv("SUCCESS_PCT_MIN", success_pct)),
        "rr_top10_min": float(os.getenv("MIN_RR_TOP10", rr_top10)),
        "rr_alt_min": float(os.getenv("MIN_RR_ALT", rr_alt)),
        "quality_min": float(os.getenv("MIN_QUALITY_SCORE", quality)),
        "market_score": market_score,
        "regime": (ctx.get("filters") or {}).get("regime", "") if ctx else "",
    }


def explain_filters(thresholds: Dict[str, float]) -> str:
    """
    מחזיר הסבר קריא על הסינונים הנוכחיים
    """
    score = thresholds.get("market_score", 0.0)
    regime = thresholds.get("regime", "")
    
    if score >= 0.3:
        mood = "🟢 Aggressive (שוק מצוין)"
    elif score >= 0.0:
        mood = "🟡 Balanced (שוק בינוני)"
    elif score >= -0.3:
        mood = "🟠 Conservative (שוק חלש)"
    else:
        mood = "🔴 Very Conservative (שוק גרוע)"
    
    lines = [
        f"Market Mood: {mood}",
        f"Regime: {regime or 'Unknown'}",
        f"Success%: ≥{thresholds['success_pct_min']:.1f}%",
        f"RR Top10: ≥{thresholds['rr_top10_min']:.2f}",
        f"RR Alts: ≥{thresholds['rr_alt_min']:.2f}",
        f"Quality: ≥{thresholds['quality_min']:.1f}/10",
    ]
    return "\n".join(lines)


__all__ = [
    "get_dynamic_thresholds",
    "calculate_market_score",
    "explain_filters",
]
