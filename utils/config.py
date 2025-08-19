# utils/config.py
import os

def _as_bool(v, default=False):
    if v is None:
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "y", "on")

def _as_int(v, default):
    try:
        return int(str(v).strip())
    except Exception:
        return default

def _as_float(v, default):
    try:
        return float(str(v).strip())
    except Exception:
        return default

# ---------- Trading execution / safety ----------
EXECUTE_TRADES = _as_bool(os.getenv("EXECUTE_TRADES"), False)
BINANCE_SKIP_ACCOUNT_MUTATIONS = _as_bool(os.getenv("BINANCE_SKIP_ACCOUNT_MUTATIONS"), True)
BINANCE_FORCE_HEDGE_MODE = _as_bool(os.getenv("BINANCE_FORCE_HEDGE_MODE"), False)
MAX_LEVERAGE = _as_int(os.getenv("MAX_LEVERAGE"), 35)

# ---------- Auto Executor / Scanner ----------
AUTO_RUN = _as_bool(os.getenv("AUTO_RUN"), False)
ENABLE_AUTO_TRADING = _as_bool(os.getenv("ENABLE_AUTO_TRADING"), False)
SCAN_INTERVAL = _as_int(os.getenv("SCAN_INTERVAL"), 60)
MIN_QUALITY_SCORE = _as_float(os.getenv("MIN_QUALITY_SCORE"), 6.0)
DEFAULT_INTERVAL = os.getenv("DEFAULT_INTERVAL", "15m")
TRENDING_ONLY = _as_bool(os.getenv("TRENDING_ONLY"), False)

# ---------- Limits / Payload control ----------
RESPONSE_MAX_BYTES = _as_int(os.getenv("RESPONSE_MAX_BYTES"), 1_048_576)  # 1MB ברירת מחדל
SCAN_MAX_LIMIT = _as_int(os.getenv("SCAN_MAX_LIMIT"), 20)
EXPOSE_LIMITS = _as_bool(os.getenv("EXPOSE_LIMITS"), True)  # אם False—לא נחשוף ב-/health

# ---------- Risk bounds (אחוזים) ----------
SL_MIN_PCT = _as_float(os.getenv("SL_MIN_PCT"), 0.20)
SL_MAX_PCT = _as_float(os.getenv("SL_MAX_PCT"), 5.00)
TP_MIN_PCT = _as_float(os.getenv("TP_MIN_PCT"), 0.30)
TP_MAX_PCT = _as_float(os.getenv("TP_MAX_PCT"), 8.00)

# ---------- Cooldown / placement control ----------
SYMBOL_COOLDOWN_SEC = _as_int(os.getenv("SYMBOL_COOLDOWN_SEC"), 600)
MAX_TRADES_PER_TICK = _as_int(os.getenv("MAX_TRADES_PER_TICK"), 3)

# ---------- SL/TP engine ----------
SLTP_MIN_PCT_FLOOR = _as_float(os.getenv("SLTP_MIN_PCT_FLOOR"), 0.003)
SLTP_TP_PCT_FLOOR  = _as_float(os.getenv("SLTP_TP_PCT_FLOOR"), 0.006)
SLTP_ATR_SL_MULT   = _as_float(os.getenv("SLTP_ATR_SL_MULT"), 1.5)
SLTP_ATR_TP_MULT   = _as_float(os.getenv("SLTP_ATR_TP_MULT"), 2.5)














