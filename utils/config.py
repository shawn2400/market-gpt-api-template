# utils/config.py
from __future__ import annotations
import os

def _as_bool(v: str | None, default: bool = False) -> bool:
    if v is None:
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "y", "on")

def _as_int(v: str | None, default: int) -> int:
    try:
        return int(str(v).strip())
    except Exception:
        return default

def _as_float(v: str | None, default: float) -> float:
    try:
        return float(str(v).strip())
    except Exception:
        return default

# ---------- Versions / metadata ----------
ALGOGPT_VERSION   = os.getenv("ALGOGPT_VERSION", "2.14.3")
STRATEGY_VERSION  = os.getenv("STRATEGY_VERSION", ALGOGPT_VERSION)

# ---------- Limits / stability ----------
RESPONSE_MAX_BYTES = _as_int(os.getenv("RESPONSE_MAX_BYTES"), 1_048_576)  # 1MB
SCAN_MAX_LIMIT     = _as_int(os.getenv("SCAN_MAX_LIMIT"), 20)
EXPOSE_LIMITS      = _as_bool(os.getenv("EXPOSE_LIMITS"), True)

# ---------- Trading execution / safety ----------
EXECUTE_TRADES                   = _as_bool(os.getenv("EXECUTE_TRADES"), False)
BINANCE_SKIP_ACCOUNT_MUTATIONS   = _as_bool(os.getenv("BINANCE_SKIP_ACCOUNT_MUTATIONS"), True)
BINANCE_FORCE_HEDGE_MODE         = _as_bool(os.getenv("BINANCE_FORCE_HEDGE_MODE"), False)
MAX_LEVERAGE                     = _as_int(os.getenv("MAX_LEVERAGE"), 35)
MAX_TRADE_BUDGET                 = _as_float(os.getenv("MAX_TRADE_BUDGET"), 100.0)

# ---------- Auto Executor / Scanner ----------
AUTO_RUN             = _as_bool(os.getenv("AUTO_RUN"), False)
ENABLE_AUTO_TRADING  = _as_bool(os.getenv("ENABLE_AUTO_TRADING"), False)
SCAN_INTERVAL        = _as_int(os.getenv("SCAN_INTERVAL"), 60)                 # שניות
MIN_QUALITY_SCORE    = _as_float(os.getenv("MIN_QUALITY_SCORE"), 6.0)
TRENDING_ONLY        = _as_bool(os.getenv("TRENDING_ONLY"), False)             # ← יותר מועמדים? קבע False
DEFAULT_INTERVAL     = os.getenv("DEFAULT_INTERVAL", "15m")

# ---------- SL/TP bounds (אחוזים) ----------
SL_MIN_PCT = _as_float(os.getenv("SL_MIN_PCT"), 0.20)
SL_MAX_PCT = _as_float(os.getenv("SL_MAX_PCT"), 5.00)
TP_MIN_PCT = _as_float(os.getenv("TP_MIN_PCT"), 0.30)
TP_MAX_PCT = _as_float(os.getenv("TP_MAX_PCT"), 8.00)

# ---------- Cooldown / placement control ----------
SYMBOL_COOLDOWN_SEC  = _as_int(os.getenv("SYMBOL_COOLDOWN_SEC"), 600)
MAX_TRADES_PER_TICK  = _as_int(os.getenv("MAX_TRADES_PER_TICK"), 3)















