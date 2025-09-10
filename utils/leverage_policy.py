# utils/leverage_policy.py
from __future__ import annotations
import os, json, logging
from typing import Optional, Dict, Any

logger = logging.getLogger("algogpt.leverage")

# גבולות כלליים מהסביבה
_MIN_LEV = int(os.getenv("MIN_LEVERAGE", "5"))
_MAX_LEV = int(os.getenv("MAX_LEVERAGE", "35"))

# ADX safety
_ADX_SAFETY_MAX = int(os.getenv("OPS_ADX_SAFETY_MAX_LEVERAGE", "15"))
# cutoff אחרון הוא "גבוה" – רק מעליו אפשר לשחרר מעבר ל־_ADX_SAFETY_MAX
try:
    _ADX_CUTOFFS = [int(x) for x in os.getenv("OPS_ADX_LEVERAGE_CUTOFFS", "20,25,30").split(",") if x.strip()]
except Exception:
    _ADX_CUTOFFS = [20, 25, 30]
_LAST_CUTOFF = max(_ADX_CUTOFFS) if _ADX_CUTOFFS else 30

# מפת ADX→מינוף מומלץ (JSON באותו פורמט שסיפקת)
# דוגמה ברירת מחדל בטוחה אם אין ENV
try:
    _LEV_ADX_MAP = json.loads(os.getenv("LEV_ADX_MAP_JSON", '{"30":15,"25":12,"20":9,"0":7}'))
    # ודא שמפתחות הם ints
    _LEV_ADX_MAP = {int(k): int(v) for k, v in _LEV_ADX_MAP.items()}
except Exception:
    _LEV_ADX_MAP = {30: 15, 25: 12, 20: 9, 0: 7}

# Caps פר־סימבול
try:
    _SYMBOL_CAPS = json.loads(os.getenv("LEVERAGE_SYMBOL_CAPS", '{}'))
    _SYMBOL_CAPS = {str(k).upper(): int(v) for k, v in _SYMBOL_CAPS.items()}
except Exception:
    _SYMBOL_CAPS = {}

# "שחקנים בעייתיים" – cap כללי (אם תרצה לחבר ל־bad_actor_store)
_BAD_ACTOR_MAX = int(os.getenv("BAD_ACTOR_MAX_LEVERAGE", "8"))

# Degrade דינמי ממנגנון ה־ops (drift וכו')
def _get_degrade_cap() -> Optional[int]:
    try:
        from utils.runtime_counters import get_degrade_cap  # type: ignore
        return get_degrade_cap()
    except Exception:
        return None

def _bad_actor_cap(symbol: Optional[str]) -> Optional[int]:
    """אם קיים מודול bad_actor_store, ננסה למשוך ממנו cap; אחרת כלום."""
    if not symbol:
        return None
    try:
        from utils.bad_actor_store import get_symbol_cap, is_bad_actor  # type: ignore
        cap = get_symbol_cap(symbol)
        if cap is not None:
            return int(cap)
        # אם רק "בעייתי" ללא cap ספציפי – החזר ברירת מחדל
        if is_bad_actor(symbol):
            return _BAD_ACTOR_MAX
    except Exception:
        pass
    return None

def _apply_adx_map(adx: float, proposed: int) -> int:
    """
    מצא את המפתח הגדול ביותר <= ADX וקבע cap בהתאם למפה; החזר המינימום בין המוצע ל־cap.
    """
    best_key = max((k for k in _LEV_ADX_MAP.keys() if adx >= k), default=None)
    if best_key is None:
        return int(proposed)
    cap = int(_LEV_ADX_MAP.get(best_key, proposed))
    return int(min(proposed, cap))

def _apply_adx_safety(adx: float, current: int) -> int:
    """
    אם ADX נמוך מה-cutoff הגבוה, אל תחרוג מ־_ADX_SAFETY_MAX.
    רק כש־ADX >= cutoff הגבוה – מותר לעבור את ה־_ADX_SAFETY_MAX (עד MAX_LEVERAGE).
    """
    if adx < _LAST_CUTOFF:
        return int(min(current, _ADX_SAFETY_MAX))
    return int(current)

def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))

def adjust_leverage(adx: float, proposed_leverage: int, *, symbol: Optional[str] = None) -> int:
    """
    מדיניות מינוף דינמית:
      1) התחלה: proposed_leverage מהסקנר/לוגיקה שלך
      2) cap לפי מפה ADX→LEV (ENV)
      3) ADX safety: אם adx < cutoff הגבוה – cap ל־OPS_ADX_SAFETY_MAX_LEVERAGE
      4) cap פר־סימבול (ENV)
      5) cap "שחקן בעייתי" (מודול חיצוני/ENV)
      6) cap Degrade דינמי (ops: drift/vitals)
      7) clamp ל־[MIN_LEVERAGE, MAX_LEVERAGE]
    """
    lev = int(proposed_leverage)

    # 2) מפה ADX
    lev = _apply_adx_map(float(adx), lev)

    # 3) ADX safety
    lev = _apply_adx_safety(float(adx), lev)

    # 4) סימבול קאפ
    if symbol:
        cap_sym = _SYMBOL_CAPS.get(str(symbol).upper())
        if cap_sym is not None:
            lev = min(lev, int(cap_sym))

    # 5) bad-actor cap (אם יש)
    bac = _bad_actor_cap(symbol)
    if bac is not None:
        lev = min(lev, int(bac))

    # 6) Degrade דינמי
    dcap = _get_degrade_cap()
    if dcap is not None:
        lev = min(lev, int(dcap))

    # 7) Clamp סופי
    lev = _clamp(lev, _MIN_LEV, _MAX_LEV)

    logger.debug({"event": "adjust_leverage",
                  "symbol": symbol, "adx": adx, "proposed": proposed_leverage,
                  "final": lev})
    return int(lev)

__all__ = ["adjust_leverage"]




