# utils/leverage_policy.py
from __future__ import annotations
import os, json, logging, time
from typing import Dict, Any, Optional, Tuple

logger = logging.getLogger("algogpt.levpolicy")

# Dynamic Leverage v2.0 integration
DYNAMIC_LEVERAGE_MODE = os.getenv("DYNAMIC_LEVERAGE_MODE", "0").lower() in ("1", "true", "yes")

if DYNAMIC_LEVERAGE_MODE:
    try:
        from utils.dynamic_leverage import get_dynamic_leverage_calculator
        logger.info("🚀 Dynamic Leverage v2.0 ENABLED - using hybrid intelligent system")
    except ImportError:
        logger.warning("Dynamic Leverage requested but module not found, falling back to static policy")
        DYNAMIC_LEVERAGE_MODE = False

# ──────────────────────────────────────────────────────────────────────────────
# ENV helpers
# ──────────────────────────────────────────────────────────────────────────────
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

# ──────────────────────────────────────────────────────────────────────────────
# Static/global limits (ENV)
# ──────────────────────────────────────────────────────────────────────────────
MAX_LEVERAGE = _get_env_int("MAX_LEVERAGE", 35)
MIN_LEVERAGE = _get_env_int("MIN_LEVERAGE", 5)

# ADX safety ceiling (soft cap, לפני כל שאר הקאפים)
ADX_SAFETY_MAX_LEV = _get_env_int("OPS_ADX_SAFETY_MAX_LEVERAGE", 15)

# Degrade-on-drift (מוזן ע"י runtime_counters.ops_tick_safe)
DRIFT_DEGRADE_ENABLE = os.getenv("OPS_DRIFT_DEGRADE_ENABLE", "1").lower() in ("1","true","on","yes")
DRIFT_DEGRADE_MIN_BPS = _get_env_float("OPS_DRIFT_DEGRADE_MIN_BPS", 30.0)
DEGRADE_MAX_LEV       = _get_env_int("OPS_DEGRADE_MAX_LEVERAGE", 12)

# מיפוי ADX→מינוף (טבלת מדרגות). המפתח הוא סף ADX (string/מספר), הערך הוא מינוף מקסימלי.
LEV_ADX_MAP = _get_env_json_map("LEV_ADX_MAP_JSON", {"30": 15, "25": 12, "20": 9, "0": 7})

# Caps פר-סימבול (e.g. {"BTCUSDT": 15, "1000PEPEUSDT": 8})
SYMBOL_CAPS = _get_env_json_map_str_int("LEVERAGE_SYMBOL_CAPS")

# Heuristic ל־1000-tokens
BAD_ACTOR_MAX_LEVERAGE = _get_env_int("BAD_ACTOR_MAX_LEVERAGE", 0)  # 0=disabled

# היסטרזיס/Rate-limit לשינוי מינוף (מניעת פליפ-פלופ)
LEV_HYST_MIN_DELTA = _get_env_int("LEV_HYST_MIN_DELTA", 1)    # שינוי מינ' כדי לאשר עדכון
LEV_MIN_UPDATE_SEC = _get_env_int("LEV_MIN_UPDATE_SEC", 25)   # זמן מינ' בין עדכונים פר-סימבול

# התאמה קלה לפי Governor (אופציונלי, נשלף מה־ENV)
GOVERNOR_MODE = os.getenv("MODE_GOVERNOR", os.getenv("GOVERNOR_MODE", "BALANCED")).strip().upper()
GOV_STRICT_DELTA   = _get_env_int("LEV_GOV_STRICT_DELTA", 2)     # הורדה במוד STRICT
GOV_AGGR_DELTA_CAP = _get_env_int("LEV_GOV_AGGR_BONUS", 2)       # בונוס תקרה במוד AGGRESSIVE

# Scaling עדין לפי איכות/ATR (לא חובה, מבוסס kwargs אם נמסר)
QUAL_BONUS_AT_Q10 = _get_env_int("LEV_QUAL_BONUS_AT_Q10", 2)     # +2 מדרגות באיכות 10
ATR_PCT_HARD_CAP  = _get_env_float("LEV_ATR_PCT_HARD_CAP", 3.0)  # אם atr_pct>3% קבע תקרה שמרנית
ATR_PCT_CAP_LEV   = _get_env_int("LEV_ATR_PCT_CAP_LEV", 8)

# ──────────────────────────────────────────────────────────────────────────────
# Runtime drift source (מוזן חיצונית)
# ──────────────────────────────────────────────────────────────────────────────
def _get_last_drift_bps() -> float:
    try:
        from utils.runtime_counters import price_get_last_drift_bps
        return float(price_get_last_drift_bps(max_age_sec=60))
    except Exception:
        return 0.0

# ──────────────────────────────────────────────────────────────────────────────
# Internal state (log only when changed + היסטרזיס)
# ──────────────────────────────────────────────────────────────────────────────
_last_effective_map: Dict[str, int] = {}
_last_set_ts: Dict[str, float] = {}

def _note_change(symbol: str, prev: Optional[int], new: int, ctx: Dict[str, Any]) -> None:
    if prev is None or int(prev) != int(new):
        payload = {"event": "leverage.adjust", "symbol": symbol, "old": prev, "new": new, **ctx}
        logger.info(payload)

def _adx_map_recommend(adx: float) -> Optional[int]:
    """
    החזרת מינוף מומלץ לפי טבלת LEV_ADX_MAP — הערך עבור סף ה-ADX הגבוה ביותר שאינו עולה על ADX.
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

def _apply_symbol_caps(symbol: Optional[str], lev: int) -> Tuple[int, Optional[str], Optional[int]]:
    if not symbol:
        return lev, None, None
    sym = symbol.upper()
    # Cap מפורש מה־ENV
    if sym in SYMBOL_CAPS:
        return min(lev, int(SYMBOL_CAPS[sym])), "symbol_cap", int(SYMBOL_CAPS[sym])
    # Heuristic ל־1000-tokens
    if BAD_ACTOR_MAX_LEVERAGE > 0 and sym.startswith("1000"):
        return min(lev, BAD_ACTOR_MAX_LEVERAGE), "bad_actor_cap", BAD_ACTOR_MAX_LEVERAGE
    return lev, None, None

def _apply_governor_caps(base: int) -> int:
    if GOVERNOR_MODE == "STRICT":
        return max(MIN_LEVERAGE, base - GOV_STRICT_DELTA)
    if GOVERNOR_MODE == "AGGRESSIVE":
        return min(MAX_LEVERAGE, base + GOV_AGGR_DELTA_CAP)
    return base

# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────
def adjust_leverage(adx: float, proposed: int, symbol: Optional[str] = None, **kwargs) -> int:
    """
    קביעת מינוף אפקטיבי עם רבדים של Caps ושכלולים:
    
    🚀 DYNAMIC LEVERAGE v2.0:
      אם DYNAMIC_LEVERAGE_MODE=1, משתמש במערכת ההיברידית החכמה:
      - Multi-factor confidence scoring
      - 3-Layer safety guards
      - Market regime detection
      - Portfolio protection
      - Recovery mode
      
    📊 STATIC LEVERAGE (fallback):
      1) התחלה מ־proposed (פלט האסטרטגיה).
      2) המלצת טבלת ADX→LEV (min).
      3) תקרת בטיחות ADX (OPS_ADX_SAFETY_MAX_LEVERAGE).
      4) Caps פר-סימבול / Heuristic 1000-tokens.
      5) Degrade על סמך Price-Drift (אם פעיל).
      6) התאמות עדינות: ATR% גבוה → Cap שמרני; Governor STRICT/AGGRESSIVE; איכות (quality) אם נמסרה.
      7) היסטרזיס/Rate-limit: חסימת שינויים קטנים/תכופים.
      8) Clamp לטווח [MIN_LEVERAGE..MAX_LEVERAGE].

    פרמטרים אופציונליים ב-kwargs:
      - quality: float [0..10]  → איכות סיגנל. עשוי להוסיף עד +QUAL_BONUS_AT_Q10 במקסימום.
      - atr_pct: float          → ATR כאחוז מהמחיר. אם גדול מ-ATR_PCT_HARD_CAP → Cap ל-ATR_PCT_CAP_LEV.
      - current_price: float    → מחיר נוכחי (נדרש ל-Dynamic Leverage)
      - win_rate: float         → Win rate 0-1 (אופציונלי, ל-Dynamic Leverage)
      - drift_bps: float        → אם ברצונך לכפות ערך Drift חיצוני; אם לא — יישאב אוטומטית.
      - regime: str             → "STRICT"/"BALANCED"/"AGGRESSIVE" (אם רוצים לעקוף ENV עכשווי).
    """
    
    # 🚀 Try Dynamic Leverage v2.0 first
    if DYNAMIC_LEVERAGE_MODE and symbol:
        try:
            calc = get_dynamic_leverage_calculator()
            
            # Extract parameters for dynamic calculator
            quality = kwargs.get("quality", 5.0)  # Default to neutral if not provided
            atr_pct = kwargs.get("atr_pct", 0.02)  # Default 2% if not provided
            current_price = kwargs.get("current_price", 0.0)
            win_rate = kwargs.get("win_rate")
            market_regime = kwargs.get("market_regime")
            
            if current_price > 0:
                result = calc.calculate_leverage(
                    trade_quality=float(quality),
                    symbol=symbol,
                    atr_pct=float(atr_pct),
                    current_price=float(current_price),
                    adx=float(adx) if adx else None,
                    win_rate=float(win_rate) if win_rate else None,
                    market_regime=market_regime,
                    **kwargs
                )
                
                logger.info(
                    f"🚀 Dynamic Leverage: {symbol} → {result['leverage']}x | "
                    f"Confidence: {result['confidence_score'].total_score:.1f}/10 | "
                    f"Guards: {len(result['guards_applied'])}"
                )
                
                return result["leverage"]
            else:
                logger.warning(f"Dynamic Leverage: Missing current_price for {symbol}, falling back to static")
        except Exception as e:
            logger.error(f"Dynamic Leverage failed for {symbol}: {e}, falling back to static")
    
    # 📊 Fallback to static leverage policy
    base = int(proposed)
    ctx: Dict[str, Any] = {
        "adx": round(float(adx), 2),
        "proposed": int(proposed),
        "max_lev": int(MAX_LEVERAGE),
        "min_lev": int(MIN_LEVERAGE),
        "gov_mode": kwargs.get("regime", GOVERNOR_MODE),
    }

    # 2) המלצת טבלת ADX
    adx_rec = _adx_map_recommend(float(adx))
    if adx_rec is not None:
        base = min(base, int(adx_rec))
        ctx["adx_map_rec"] = int(adx_rec)

    # 3) תקרת בטיחות ADX
    if ADX_SAFETY_MAX_LEV > 0:
        base = min(base, ADX_SAFETY_MAX_LEV)
        ctx["adx_safety_cap"] = int(ADX_SAFETY_MAX_LEV)

    # 4) Caps פר-סימבול / 1000-tokens
    base, cap_kind, cap_val = _apply_symbol_caps(symbol, base)
    if cap_kind:
        ctx[cap_kind] = int(cap_val or 0)

    # 5) Price-drift → Degrade cap
    drift_bps = float(kwargs.get("drift_bps")) if kwargs.get("drift_bps") is not None else _get_last_drift_bps()
    ctx["drift_bps"] = round(drift_bps, 1)
    if DRIFT_DEGRADE_ENABLE and drift_bps >= DRIFT_DEGRADE_MIN_BPS:
        base = min(base, DEGRADE_MAX_LEV)
        ctx["degrade_cap"] = int(DEGRADE_MAX_LEV)

    # 6a) ATR% גבוה → Cap שמרני
    try:
        atr_pct = float(kwargs.get("atr_pct")) if kwargs.get("atr_pct") is not None else None
    except Exception:
        atr_pct = None
    if atr_pct is not None:
        ctx["atr_pct"] = round(float(atr_pct), 3)
        if float(atr_pct) >= ATR_PCT_HARD_CAP:
            base = min(base, ATR_PCT_CAP_LEV)
            ctx["atr_cap"] = int(ATR_PCT_CAP_LEV)

    # 6b) Governor STRICT/AGGRESSIVE (רק התאמה עדינה; clamp סופי ייעשה בסוף)
    gov = str(kwargs.get("regime", GOVERNOR_MODE)).upper()
    base = _apply_governor_caps(base)
    ctx["gov_applied"] = gov

    # 6c) איכות (quality 0..10) — בונוס מתון בלבד
    q = kwargs.get("quality")
    if q is not None:
        try:
            qf = max(0.0, min(10.0, float(q)))
            # בונוס לינארי עד QUAL_BONUS_AT_Q10 במקסימום באיכות 10, לא עוקף קאפים קודמים
            bonus = int(round((qf / 10.0) * QUAL_BONUS_AT_Q10))
            if bonus > 0:
                base = min(MAX_LEVERAGE, base + bonus)
                ctx["qual_bonus"] = int(bonus)
                ctx["quality"] = qf
        except Exception:
            pass

    # 8) Clamp גלובלי
    eff = max(MIN_LEVERAGE, min(base, MAX_LEVERAGE))

    # 7) היסטרזיס/Rate-limit לשינוי מינוף
    key = (symbol or "GLOBAL").upper()
    prev = _last_effective_map.get(key)
    now = time.time()
    last_ts = _last_set_ts.get(key, 0.0)
    if prev is not None:
        small_delta = abs(eff - prev) < LEV_HYST_MIN_DELTA
        too_soon    = (now - last_ts) < LEV_MIN_UPDATE_SEC
        if small_delta or too_soon:
            # שמור את הקודם כדי לא "לרצד" מינוף על שינויים זעירים/תכופים
            return int(prev)

    if prev != eff:
        _note_change(key, prev, eff, ctx)
        _last_effective_map[key] = eff
        _last_set_ts[key] = now

    return int(eff)

# עזר לאבחון (לא נדרש ע"י המערכת, אבל נוח ל־/status)
def current_leverage_cache() -> Dict[str, int]:
    return dict(_last_effective_map)

__all__ = ["adjust_leverage", "current_leverage_cache"]








