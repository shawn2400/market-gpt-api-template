# utils/leverage_policy.py
from __future__ import annotations
import os, json, logging
from typing import Optional, Dict

logger = logging.getLogger("algogpt.leverage_policy")

# קונפיג כללי
_MIN_LEV = int(os.getenv("MIN_LEVERAGE", "5"))
_MAX_LEV = int(os.getenv("MAX_LEVERAGE", "35"))

# אם יש דגרדה פעילה – נשתמש ב־cap משם
try:
    from utils.runtime_counters import clamp_leverage, leverage_cap, degrade_active
except Exception:
    def clamp_leverage(x: int) -> int:  # fallback: רק קלמפ בסיסי
        return int(max(_MIN_LEV, min(_MAX_LEV, x)))
    def leverage_cap() -> int:
        return _MAX_LEV
    def degrade_active() -> bool:
        return False

# Bad-Actor store (לא חובה)
_is_bad_symbol = None
try:
    from utils.bad_actor_store import is_bad_symbol as _is_bad_symbol  # type: ignore
except Exception:
    pass

BAD_ACTOR_MAX_LEVERAGE = int(os.getenv("BAD_ACTOR_MAX_LEVERAGE", "8"))

# מיפוי ADX -> מינוף מוצע (אפשר לשנות ב־ENV: LEV_ADX_MAP_JSON='{"30":15,"25":12,"20":9,"0":7}')
def _load_adx_map() -> Dict[int,int]:
    raw = os.getenv("LEV_ADX_MAP_JSON", "").strip()
    if raw:
        try:
            obj = json.loads(raw)
            out = {int(k): int(v) for k,v in obj.items()}
            return dict(sorted(out.items(), key=lambda kv: -kv[0]))  # יורד: 30→15, 25→12...
        except Exception as e:
            logger.warning({"event":"lev.map_bad_json","err":str(e)})
    # ברירת מחדל
    return {30:15, 25:12, 20:9, 0:7}

_ADX_MAP = _load_adx_map()

# קאפ פר־סימבול (אופציונלי): LEVERAGE_SYMBOL_CAPS='{"BTCUSDT":15,"1000PEPEUSDT":8}'
_sym_caps: Dict[str,int] = {}
try:
    caps_raw = os.getenv("LEVERAGE_SYMBOL_CAPS", "").strip()
    if caps_raw:
        _sym_caps = {k.upper(): int(v) for k,v in json.loads(caps_raw).items()}
except Exception as e:
    logger.warning({"event":"lev.sym_caps_bad_json","err":str(e)})

def _base_from_adx(adx: float, proposed: int) -> int:
    """נבחר בסיס לפי ADX, ואז נשקלל מול המוצע."""
    base = None
    for thr, lev in _ADX_MAP.items():
        if adx >= thr:
            base = lev
            break
    if base is None:
        base = min(proposed, _MAX_LEV)
    # ניקח את המינימום בין הבסיס למוצע (גישה שמרנית)
    return int(min(base, proposed))

def _cap_for_symbol(symbol: Optional[str]) -> Optional[int]:
    if not symbol:
        return None
    su = symbol.strip().upper()
    if su in _sym_caps:
        return int(_sym_caps[su])
    if _is_bad_symbol:
        try:
            if _is_bad_symbol(su):
                return BAD_ACTOR_MAX_LEVERAGE
        except Exception:
            pass
    return None

def adjust_leverage(adx: float, proposed_leverage: int, *, symbol: Optional[str]=None) -> int:
    """
    כלל החלטה:
      1) בסיס לפי ADX (מפה/ENV) מול המוצע → min
      2) קאפ פר־סימבול/Bad-Actor אם קיים → min
      3) אם יש Degrade פעיל → clamp_leverage() (מכבד cap דינמי מה־runtime_counters)
      4) קלמפ כללי ל־MIN/MAX
    """
    try:
        lev = _base_from_adx(float(adx), int(proposed_leverage))

        sym_cap = _cap_for_symbol(symbol)
        if sym_cap is not None:
            lev = min(lev, int(sym_cap))

        # cap דינמי מ־runtime_counters (כולל Degrade)
        lev = clamp_leverage(lev)

        # קלמפ אחרון למקרה שאין runtime_counters
        lev = int(max(_MIN_LEV, min(_MAX_LEV, lev)))
        return lev
    except Exception as e:
        logger.warning({"event":"lev.adjust_fail","err":str(e)})
        # נפילה רכה—לפחות נכבד Degrade אם יש
        try:
            return clamp_leverage(int(proposed_leverage))
        except Exception:
            return int(max(_MIN_LEV, min(_MAX_LEV, int(proposed_leverage)))))



