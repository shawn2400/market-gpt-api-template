# utils/leverage_policy.py
from __future__ import annotations
import os, json, logging
from typing import Dict, Any, Optional

logger = logging.getLogger("algogpt.levpolicy")

# --- ENV helpers ---
def _get_env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default

def _get_env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return default

def _get_env_json_map(name: str, default: Dict[str, int]) -> Dict[str, int]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        obj = json.loads(raw)
        out: Dict[str, int] = {}
        for k, v in obj.items():
            try:
                out[str(k)] = int(v)
            except Exception:
                continue
        return out or default
    except Exception:
        return default

def _get_env_json_map_str_int(name: str) -> Dict[str, int]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return {}
    try:
        obj = json.loads(raw)
        out: Dict[str, int] = {}
        for k, v in obj.items():
            try:
                out[str(k).upper()] = int(v)
            except Exception:
                continue
        return out
    except Exception:
        return {}

# --- Static/global limits from env (with sane defaults) ---
MAX_LEVERAGE = _get_env_int("MAX_LEVERAGE", 35)
MIN_LEVERAGE = _get_env_int("MIN_LEVERAGE", 5)

# ADX safety ceiling (global soft cap)
ADX_SAFETY_MAX_LEV = _get_env_int("OPS_ADX_SAFETY_MAX_LEVERAGE", 15)

# Degrade-on-drift configuration
DRIFT_DEGRADE_ENABLE = os.getenv("OPS_DRIFT_DEGRADE_ENABLE", "1").lower() in ("1","true","on","yes")
DRIFT_DEGRADE_MIN_BPS = _get_env_float("OPS_DRIFT_DEGRADE_MIN_BPS", 30.0)
DEGRADE_MAX_LEV = _get_env_int("OPS_DEGRADE_MAX_LEVERAGE", 12)

# Optional ADX→leverage mapping (step table). Keys are ADX thresholds.
LEV_ADX_MAP = _get_env_json_map("LEV_ADX_MAP_JSON", {"30": 15, "25": 12, "20": 9, "0": 7})

# Per-symbol hard caps (e.g., {"BTCUSDT": 15, "1000PEPEUSDT": 8})
SYMBOL_CAPS = _get_env_json_map_str_int("LEVERAGE_SYMBOL_CAPS")

# Heuristic low-cap guard (e.g. 1000-coins)
BAD_ACTOR_MAX_LEVERAGE = _get_env_int("BAD_ACTOR_MAX_LEVERAGE", 0)  # 0=disabled

# --- Runtime drift source (fed by runtime_counters.ops_tick_safe) ---
def _get_last_drift_bps() -> float:
    try:
        from utils.runtime_counters import price_get_last_drift_bps
        return float(price_get_last_drift_bps(max_age_sec=60))
    except Exception:
        return 0.0

# --- Internal state to log changes only when needed ---
_last_effective_map: Dict[str, int] = {}

def _note_change(symbol: str, prev: Optional[int], new: int, ctx: Dict[str, Any]) -> None:
    if prev is None or int(prev) != int(new):
        payload = {"event": "leverage.adjust", "symbol": symbol, "old": prev, "new": new, **ctx}
        logger.info(payload)

def _adx_map_recommend(adx: float) -> Optional[int]:
    """
    Finds recommended leverage from LEV_ADX_MAP by the highest threshold <= ADX.
    Returns None if map is empty.
    """
    if not LEV_ADX_MAP:
        return None
    best_k = None
    best_thr = -1.0
    for k, lev in LEV_ADX_MAP.items():
        try:
            thr = float(k)
        except Exception:
            continue
        if adx >= thr and thr > best_thr:
            best_thr = thr
            best_k = k
    return int(LEV_ADX_MAP[best_k]) if best_k is not None else None

def _apply_symbol_caps(symbol: Optional[str], lev: int) -> (int, Optional[str], Optional[int]):
    if not symbol:
        return lev, None, None
    sym = symbol.upper()
    # Explicit per-symbol cap
    if sym in SYMBOL_CAPS:
        return min(lev, int(SYMBOL_CAPS[sym])), "symbol_cap", int(SYMBOL_CAPS[sym])
    # Heuristic for 1000-tokens
    if BAD_ACTOR_MAX_LEVERAGE > 0 and sym.startswith("1000"):
        return min(lev, BAD_ACTOR_MAX_LEVERAGE), "bad_actor_cap", BAD_ACTOR_MAX_LEVERAGE
    return lev, None, None

def adjust_leverage(adx: float, proposed: int, symbol: Optional[str] = None) -> int:
    """
    Policy:
      1) Start from 'proposed' (strategy output).
      2) Apply ADX mapping suggestion (min with table value).
      3) Apply ADX safety ceiling (OPS_ADX_SAFETY_MAX_LEVERAGE).
      4) Apply per-symbol caps / 1000-heuristic.
      5) If drift degrade is active (>= OPS_DRIFT_DEGRADE_MIN_BPS), cap to DEGRADE_MAX_LEV.
      6) Clamp to [MIN_LEVERAGE .. MAX_LEVERAGE].
      7) INFO-log when effective value changes (per symbol).
    """
    base = int(proposed)
    ctx: Dict[str, Any] = {
        "adx": round(float(adx), 2),
        "proposed": int(proposed),
        "max_lev": int(MAX_LEVERAGE),
        "min_lev": int(MIN_LEVERAGE),
    }

    # 2) ADX mapping recommendation
    adx_rec = _adx_map_recommend(float(adx))
    if adx_rec is not None:
        base = min(base, int(adx_rec))
        ctx["adx_map_rec"] = int(adx_rec)

    # 3) ADX safety ceiling
    if ADX_SAFETY_MAX_LEV > 0:
        base = min(base, ADX_SAFETY_MAX_LEV)
        ctx["adx_safety_cap"] = int(ADX_SAFETY_MAX_LEV)

    # 4) Symbol caps / bad-actor heuristic
    base, cap_kind, cap_val = _apply_symbol_caps(symbol, base)
    if cap_kind:
        ctx[cap_kind] = int(cap_val or 0)

    # 5) Drift → degrade cap
    drift_bps = _get_last_drift_bps()
    ctx["drift_bps"] = round(drift_bps, 1)
    if DRIFT_DEGRADE_ENABLE and drift_bps >= DRIFT_DEGRADE_MIN_BPS:
        base = min(base, DEGRADE_MAX_LEV)
        ctx["degrade_cap"] = int(DEGRADE_MAX_LEV)

    # 6) Clamp to global limits
    eff = max(MIN_LEVERAGE, min(base, MAX_LEVERAGE))

    # 7) Log on change
    key = (symbol or "GLOBAL").upper()
    prev = _last_effective_map.get(key)
    if prev != eff:
        _note_change(key, prev, eff, ctx)
        _last_effective_map[key] = eff

    return int(eff)

__all__ = ["adjust_leverage"]







