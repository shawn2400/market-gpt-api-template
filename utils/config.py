# utils/config.py
from __future__ import annotations
import os
from typing import List

# -------- helpers --------
def _get(name: str, default: str | None = None) -> str | None:
    v = os.getenv(name)
    return v if v is not None else default

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

def _as_list(v: str | None) -> List[str]:
    if not v:
        return []
    return [x.strip() for x in v.replace(";", ",").split(",") if x.strip()]

# =========================================================
#                 GLOBAL / SERVER & LIMITS
# =========================================================
PORT                 = _as_int(_get("PORT", "10000"), 10000)
WORKERS              = _as_int(_get("WORKERS", "1"), 1)  # אם לא בשימוש בגוניקורן—לא מזיק
RESPONSE_MAX_BYTES   = _as_int(_get("RESPONSE_MAX_BYTES", "1048576"), 1048576)  # 1MB
SCAN_MAX_LIMIT       = _as_int(_get("SCAN_MAX_LIMIT", "20"), 20)               # חונק בקשות כבדות

# לוגים / CORS
LOG_LEVEL            = _get("LOG_LEVEL", "INFO") or "INFO"
CORS_ALLOW_ORIGINS   = _get("CORS_ALLOW_ORIGINS", "*") or "*"

# אבטחה
SECURITY_ALLOW_ALL   = _as_bool(_get("SECURITY_ALLOW_ALL", "0"), False)

# =========================================================
#                     AUTO EXECUTOR / SCANNER
# =========================================================
AUTO_RUN             = _as_bool(_get("AUTO_RUN", "false"), False)
ENABLE_AUTO_TRADING  = _as_bool(_get("ENABLE_AUTO_TRADING", "false"), False)
EXECUTE_TRADES       = _as_bool(_get("EXECUTE_TRADES", "false"), False)  # הגדרה יחידה (תוקן)
SCAN_INTERVAL        = _as_int(_get("SCAN_INTERVAL", "60"), 60)
DEFAULT_INTERVAL     = _get("DEFAULT_INTERVAL", "15m") or "15m"
MIN_QUALITY_SCORE    = _as_float(_get("MIN_QUALITY_SCORE", "6"), 6.0)
TRENDING_ONLY        = _as_bool(_get("TRENDING_ONLY", "false"), False)

# סורק – ברירות מחדל נוספות
MIN_VOLUME           = _as_float(_get("MIN_VOLUME", "1000000"), 1_000_000.0)
TOP_SYMBOLS          = _as_int(_get("TOP_SYMBOLS", "50"), 50)
TOP_VOLUME_MIN_QV    = _as_float(_get("TOP_VOLUME_MIN_QV", "0"), 0.0)

# =========================================================
#                            RISK
# =========================================================
MAX_TRADE_BUDGET         = _as_float(_get("MAX_TRADE_BUDGET", "100"), 100.0)
MAX_LEVERAGE             = _as_int(_get("MAX_LEVERAGE", "35"), 35)
RISK_PER_TRADE_PCT       = _as_float(_get("RISK_PER_TRADE_PCT", "1.0"), 1.0)
DAILY_RISK_LIMIT_PCT     = _as_float(_get("DAILY_RISK_LIMIT_PCT", "6.0"), 6.0)
PORTFOLIO_EXPOSURE_PCT   = _as_float(_get("PORTFOLIO_EXPOSURE_PCT", "25.0"), 25.0)
MAX_CONCURRENT_TRADES    = _as_int(_get("MAX_CONCURRENT_TRADES", "7"), 7)
CONF_MIN_SCALE           = _as_float(_get("CONF_MIN_SCALE", "0.6"), 0.6)
CONF_MAX_SCALE           = _as_float(_get("CONF_MAX_SCALE", "1.4"), 1.4)
ATR_LEV_SENSITIVITY      = _as_float(_get("ATR_LEV_SENSITIVITY", "0.9"), 0.9)
TSL_TO_BE_FRACTION       = _as_float(_get("TSL_TO_BE_FRACTION", "0.20"), 0.20)

# SL/TP (גבולות כלליים)
SL_MIN_PCT               = _as_float(_get("SL_MIN_PCT", "0.20"), 0.20)
SL_MAX_PCT               = _as_float(_get("SL_MAX_PCT", "5.00"), 5.00)
TP_MIN_PCT               = _as_float(_get("TP_MIN_PCT", "0.30"), 0.30)
TP_MAX_PCT               = _as_float(_get("TP_MAX_PCT", "8.00"), 8.00)

# SL/TP Engine
SLTP_MIN_PCT_FLOOR       = _as_float(_get("SLTP_MIN_PCT_FLOOR", "0.003"), 0.003)
SLTP_TP_PCT_FLOOR        = _as_float(_get("SLTP_TP_PCT_FLOOR",  "0.006"), 0.006)
SLTP_ATR_SL_MULT         = _as_float(_get("SLTP_ATR_SL_MULT",   "1.5"), 1.5)
SLTP_ATR_TP_MULT         = _as_float(_get("SLTP_ATR_TP_MULT",   "2.5"), 2.5)

# הגנות מחיר
PRICE_PROTECT_PCT        = _as_float(_get("PRICE_PROTECT_PCT", "0.25"), 0.25)
PRICE_MAX_AGE_SEC        = _as_int(_get("PRICE_MAX_AGE_SEC", "10"), 10)

# =========================================================
#                      DECISION WEIGHTS
# =========================================================
DECISION_W_QUALITY   = _as_float(_get("DECISION_W_QUALITY", "0.40"), 0.40)
DECISION_W_SUCCESS   = _as_float(_get("DECISION_W_SUCCESS", "0.25"), 0.25)
DECISION_W_SPEED     = _as_float(_get("DECISION_W_SPEED",   "0.15"), 0.15)
DECISION_W_VOLAT     = _as_float(_get("DECISION_W_VOLAT",   "0.10"), 0.10)
DECISION_W_DECORR    = _as_float(_get("DECISION_W_DECORR",  "0.10"), 0.10)

# =========================================================
#                          BINANCE
# =========================================================
BINANCE_API_KEY                  = _get("BINANCE_API_KEY", "")
BINANCE_API_SECRET               = _get("BINANCE_API_SECRET", "")
BINANCE_BACKOFF_BASE             = _as_float(_get("BINANCE_BACKOFF_BASE", "0.7"), 0.7)
BINANCE_MAX_RETRIES              = _as_int(_get("BINANCE_MAX_RETRIES", "5"), 5)
BINANCE_RECV_WINDOW              = _as_int(_get("BINANCE_RECV_WINDOW", "10000"), 10000)
BINANCE_TIME_SYNC_INTERVAL_SEC   = _as_int(_get("BINANCE_TIME_SYNC_INTERVAL_SEC", "900"), 900)
BINANCE_EXCHANGE_INFO_ON_START   = _as_bool(_get("BINANCE_EXCHANGE_INFO_ON_START", "false"), False)
BINANCE_FORCE_HEDGE_MODE         = _as_bool(_get("BINANCE_FORCE_HEDGE_MODE", "false"), False)

BINANCE_SPOT_HTTP_BASE           = _get("BINANCE_SPOT_HTTP_BASE", "https://api.binance.com") or "https://api.binance.com"
BINANCE_FUTURES_HTTP_BASE        = _get("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com") or "https://fapi.binance.com"
BINANCE_FUTURES_WS_BASE          = _get("BINANCE_FUTURES_WS_BASE", "wss://fstream.binance.com") or "wss://fstream.binance.com"
BINANCE_WS_STREAM_SUFFIX         = _get("BINANCE_WS_STREAM_SUFFIX", "/stream?streams=") or "/stream?streams="

# =========================================================
#                            OPENAI
# =========================================================
OPENAI_API_KEY          = _get("OPENAI_API_KEY", "")
OPENAI_MODEL            = _get("OPENAI_MODEL", "gpt-4o-mini") or "gpt-4o-mini"
OPENAI_TIMEOUT_SECONDS  = _as_float(_get("OPENAI_TIMEOUT_SECONDS", "30.0"), 30.0)
OPENAI_MAX_CONCURRENCY  = _as_int(_get("OPENAI_MAX_CONCURRENCY", "4"), 4)
OPENAI_BASE_URL         = _get("OPENAI_BASE_URL", "https://api.openai.com/v1") or "https://api.openai.com/v1"

# =========================================================
#                          NETWORKING
# =========================================================
EGRESS_IP_ENDPOINT      = _get("EGRESS_IP_ENDPOINT", "")
BINANCE_ALLOWED_EGRESS_IPS = _as_list(_get("BINANCE_ALLOWED_EGRESS_IPS", ""))

# =========================================================
#                          BTC ANCHOR
# =========================================================
BTC_ANCHOR_ENFORCE   = _as_bool(_get("BTC_ANCHOR_ENFORCE", "false"), False)
BTC_ANCHOR_STRONG_TH = _as_int(_get("BTC_ANCHOR_STRONG_TH", "70"), 70)
BTC_ANCHOR_WEAK_TH   = _as_int(_get("BTC_ANCHOR_WEAK_TH", "55"), 55)
BTC_ANCHOR_FRAMES    = _as_list(_get("BTC_ANCHOR_FRAMES", "15m,1h"))

# =========================================================
#                       NEWS / MACRO
# =========================================================
CRYPTO_PANIC_API_KEY   = _get("CRYPTO_PANIC_API_KEY", "") or _get("CRYPTOPANIC_API_KEY", "") or ""
NEWSAPI_API_KEY        = _get("NEWSAPI_API_KEY", "")
FRED_API_KEY           = _get("FRED_API_KEY", "")
BEA_API_KEY            = _get("BEA_API_KEY", "")
COINMARKETCAP_API_KEY  = _get("COINMARKETCAP_API_KEY", "")
COINDECK_API_KEY       = _get("COINDECK_API_KEY", "")
ETHERSCAN_API_KEY      = _get("ETHERSCAN_API_KEY", "")
CACHE_TTL_NEWS         = _as_int(_get("CACHE_TTL_NEWS", "120"), 120)

# =========================================================
#                     MISC / GRID / META
# =========================================================
PUBLIC_BASE_URL        = _get("PUBLIC_BASE_URL", "")
GRID_CONCURRENCY       = _as_int(_get("GRID_CONCURRENCY", "16"), 16)

ALGOGPT_VERSION        = _get("ALGOGPT_VERSION", "2.14.3") or "2.14.3"
STRATEGY_VERSION       = _get("STRATEGY_VERSION", "2.14.3") or "2.14.3"
GIT_COMMIT             = _get("GIT_COMMIT", "")
REQ_HASH               = _get("REQ_HASH", "")













