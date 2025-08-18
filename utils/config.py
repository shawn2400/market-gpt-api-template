# utils/config.py
import os

def _as_bool(v: str, default: bool = False) -> bool:
    if v is None:
        return default
    return str(v).strip().lower() in ("1","true","yes","y","on")

def _as_int(v: str, default: int) -> int:
    try:
        return int(str(v).strip())
    except Exception:
        return default

def _as_float(v: str, default: float) -> float:
    try:
        return float(str(v).strip())
    except Exception:
        return default

# ---------- Trading execution / safety ----------
EXECUTE_TRADES = _as_bool(os.getenv("EXECUTE_TRADES", "false"))                # ביצוע אמיתי בבורסה
BINANCE_SKIP_ACCOUNT_MUTATIONS = _as_bool(os.getenv("BINANCE_SKIP_ACCOUNT_MUTATIONS", "true"))
BINANCE_FORCE_HEDGE_MODE      = _as_bool(os.getenv("BINANCE_FORCE_HEDGE_MODE", "false"))
MAX_LEVERAGE                  = _as_int(os.getenv("MAX_LEVERAGE", "35"), 35)

# ---------- Auto Executor / Scanner ----------
AUTO_RUN             = _as_bool(os.getenv("AUTO_RUN", "false"))                # אם true – יופעל אוטומטית ב-startup
ENABLE_AUTO_TRADING  = _as_bool(os.getenv("ENABLE_AUTO_TRADING", "false"))     # אם false – הסורק ב-NOOP (רק לוגים)
EXECUTE_TRADES       = _as_bool(os.getenv("EXECUTE_TRADES", "false"))          # שומר על העדפה כאן גם
SCAN_INTERVAL        = _as_int(os.getenv("SCAN_INTERVAL", "60"), 60)           # שניות בין טיקים
MIN_QUALITY_SCORE    = _as_float(os.getenv("MIN_QUALITY_SCORE", "6"), 6.0)
MAX_TRADE_BUDGET     = _as_float(os.getenv("MAX_TRADE_BUDGET", "100"), 100.0)
TRENDING_ONLY        = _as_bool(os.getenv("TRENDING_ONLY", "true"))
DEFAULT_INTERVAL     = os.getenv("DEFAULT_INTERVAL", "15m")

# ---------- SL/TP bounds (אחוזים) ----------
SL_MIN_PCT = _as_float(os.getenv("SL_MIN_PCT", "0.20"), 0.20)   # 0.20%
SL_MAX_PCT = _as_float(os.getenv("SL_MAX_PCT", "5.00"), 5.00)   # 5.00%
TP_MIN_PCT = _as_float(os.getenv("TP_MIN_PCT", "0.30"), 0.30)   # 0.30%
TP_MAX_PCT = _as_float(os.getenv("TP_MAX_PCT", "8.00"), 8.00)   # 8.00%

# ---------- Cooldown / placement control ----------
SYMBOL_COOLDOWN_SEC  = _as_int(os.getenv("SYMBOL_COOLDOWN_SEC", "600"), 600)
MAX_TRADES_PER_TICK  = _as_int(os.getenv("MAX_TRADES_PER_TICK", "3"), 3)

# ---------- SL/TP engine (קיים כבר אצלך – משאיר בעקביות) ----------
SLTP_MIN_PCT_FLOOR = _as_float(os.getenv("SLTP_MIN_PCT_FLOOR", "0.003"), 0.003)
SLTP_TP_PCT_FLOOR  = _as_float(os.getenv("SLTP_TP_PCT_FLOOR",  "0.006"), 0.006)
SLTP_ATR_SL_MULT   = _as_float(os.getenv("SLTP_ATR_SL_MULT",   "1.5"),   1.5)
SLTP_ATR_TP_MULT   = _as_float(os.getenv("SLTP_ATR_TP_MULT",   "2.5"),   2.5)












