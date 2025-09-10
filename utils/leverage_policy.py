# utils/leverage_policy.py
from __future__ import annotations
import os, json, logging
from typing import Dict, Any, Optional

logger = logging.getLogger("algogpt.leverage")

# ==== ENV / defaults ====
_DEF_LEV_BY_ADX = {30: 15, 25: 12, 20: 9, 0: 7}
_MIN_LEV = int(os.getenv("MIN_LEVERAGE", "5"))
_MAX_LEV = int(os.getenv("MAX_LEVERAGE", "35"))

def _parse_json_env(name: str, default: Dict[str, Any]) -> Dict[str, Any]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        d = json.loads(raw)
        if isinstance(d, dict):
            return d
    except Exception:
        pass
    return default

LEV_BY_ADX: Dict[int,int] = {int(k): int(v) for k, v in _parse_json_env("LEV_ADX_MAP_JSON", _DEF_LEV_BY_ADX).items()}
SYMBOL_CAPS: Dict[str,int] = {str(k).upper(): int(v) for k, v in _parse_json_env("LEVERAGE_SYMBOL_CAPS", {}).items()}

BAD_ACTOR_MAX_LEVERAGE = os.getenv("BAD_ACTOR_MAX_LEVERAGE", "").strip()
BAD_ACTOR_MAX_LEVERAGE = int(BAD_ACTOR_MAX_LEVERAGE) if BAD_ACTOR_MAX_LEVERAGE else None

OPS_DEGRADE_MAX_LEVERAGE = int(os.getenv("OPS_DEGRADE_MAX_LEVERAGE", "12"))
OPS_DRIFT_DEGRADE_ENABLE = os.getenv("OPS_DRIFT_DEGRADE_ENABLE", "1").lower() in ("1","true","yes","on")
OPS_DRIFT_DEGRADE_MIN_BPS = float(os.getenv("OPS_DRIFT_DEGRADE_MIN_BPS", "30"))

# אופציונלי: “תקרת בטיחות” קשיחה כש־ADX נמוך (אם רוצים מעבר למפה)
OPS_ADX_SAFETY_MAX_LEVERAGE = int(os.getenv("OPS_ADX_SAFETY_MAX_LEVERAGE", "15"))

# מקור לדריפט (ממודול המונים)
try:
    from utils.runtime_counters import price_get_last_drift_bps
except Exception:
    def price_get_last_drift_bps(*a, **k): return 0.0  # type: ignore

def _cap_by_adx(adx: float) -> int:
    # בחר את ה-threshold הגבוה ביותר ש<= ADX
    best_cap = _MAX_LEV
    best_thr = -1
    for thr, cap in LEV_BY_ADX.items():
        if adx >= thr and thr >= best_thr:
            best_thr = thr
            best_cap = int(cap)
    return int(best_cap)

def adjust_leverage(adx: float, proposed: int, symbol: Optional[str] = None) -> int:
    """החזרת מינוף אחרי קאפ לפי ADX/סימבול/דריפט/בטיחות. לוג INFO על כל שינוי."""
    reasons = []
    before = int(proposed)
    out = int(proposed)

    # 1) מפה לפי ADX
    cap_adx = _cap_by_adx(float(adx))
    if out > cap_adx:
        reasons.append(f"ADX_MAP({adx:.1f}→{cap_adx})")
        out = cap_adx

    # 2) תקרת בטיחות אופציונלית
    if out > OPS_ADX_SAFETY_MAX_LEVERAGE:
        reasons.append(f"SAFETY_MAX({OPS_ADX_SAFETY_MAX_LEVERAGE})")
        out = OPS_ADX_SAFETY_MAX_LEVERAGE

    # 3) קאפ פר-סימבול
    su = str(symbol or "").upper()
    if su and su in SYMBOL_CAPS and out > SYMBOL_CAPS[su]:
        reasons.append(f"SYMBOL_CAP({su}:{SYMBOL_CAPS[su]})")
        out = SYMBOL_CAPS[su]

    # 4) BAD_ACTOR גלובלי (אם הוגדר)
    if BAD_ACTOR_MAX_LEVERAGE is not None and out > BAD_ACTOR_MAX_LEVERAGE:
        reasons.append(f"BAD_ACTOR({BAD_ACTOR_MAX_LEVERAGE})")
        out = BAD_ACTOR_MAX_LEVERAGE

    # 5) Degrade על דריפט מחיר
    if OPS_DRIFT_DEGRADE_ENABLE:
        drift_bps = float(price_get_last_drift_bps(max_age_sec=60))
        if drift_bps >= OPS_DRIFT_DEGRADE_MIN_BPS and out > OPS_DEGRADE_MAX_LEVERAGE:
            reasons.append(f"DRIFT_DEGRADE({drift_bps:.1f}bps→{OPS_DEGRADE_MAX_LEVERAGE})")
            out = OPS_DEGRADE_MAX_LEVERAGE

    # גבולות סופיים
    out = max(_MIN_LEV, min(out, _MAX_LEV))

    if out != before:
        logger.info({
            "event": "leverage_adjust",
            "symbol": su or None,
            "adx": float(adx),
            "proposed": before,
            "final": out,
            "reasons": reasons,
        })
    return int(out)





