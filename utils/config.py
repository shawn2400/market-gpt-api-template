# utils/config.py
import os
import logging

# ---------- Helpers ----------
def _get_bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return str(val).strip().lower() in ("1", "true", "yes", "y", "on")

def _get_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except Exception:
        return default

def _get_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except Exception:
        return default

def _get_str(name: str, default: str) -> str:
    v = os.getenv(name, default)
    return v.strip() if isinstance(v, str) else default

def _mask(s: str, keep: int = 4) -> str:
    if not s:
        return ""
    s = str(s)
    return s[:keep] + "…" if len(s) > keep else "*" * len(s)

def _clamp(val, lo, hi):
    try:
        x = float(val)
    except Exception:
        return lo
    return max(lo, min(hi, x))

# ---------- Core runtime ----------
AUTO_RUN                 = _get_bool("AUTO_RUN", True)
SCAN_INTERVAL            = _get_int("SCAN_INTERVAL", 60)
DEFAULT_INTERVAL         = _get_str("DEFAULT_INTERVAL", "15m")

MIN_QUALITY_SCORE        = _get_int("MIN_QUALITY_SCORE", 6)
MAX_TRADE_BUDGET         = _get_float("MAX_TRADE_BUDGET", 100.0)
MIN_VOLUME               = _get_int("MIN_VOLUME", 1_000_000)
TOP_SYMBOLS              = int(_clamp(_get_int("TOP_SYMBOLS", 30), 1, 50))
TRENDING_ONLY            = _get_bool("TRENDING_ONLY", True)

# קונקרנסי עבור סריקות (בשימוש scanner_utils)
SCAN_CONCURRENCY         = int(_clamp(_get_int("SCAN_CONCURRENCY", 5), 1, 50))

# Prices & WS safety
PRICE_PROTECT_PCT        = _get_float("PRICE_PROTECT_PCT", 0.25)
PRICE_MAX_AGE_SEC        = _get_int("PRICE_MAX_AGE_SEC", 10)
MAX_STREAMS_PER_CONN     = _get_int("MAX_STREAMS_PER_CONN", 200)

# REST cooldown (ban-aware)
REST_COOLDOWN_SEC        = _get_int("REST_COOLDOWN_SEC", 900)
REST_MAX_COOLDOWN_SEC    = _get_int("REST_MAX_COOLDOWN_SEC", 3600)

# ---------- Networking / Bind ----------
PORT                     = _get_int("PORT", int(os.environ.get("PORT", "8000")))

# ---------- Binance ----------
BINANCE_API_KEY          = _get_str("BINANCE_API_KEY", "")
BINANCE_API_SECRET       = _get_str("BINANCE_API_SECRET", "")

BINANCE_SPOT_HTTP_BASE   = _get_str("BINANCE_SPOT_HTTP_BASE", "https://api.binance.com")
BINANCE_FUTURES_HTTP_BASE= _get_str("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com")
BINANCE_FUTURES_WS_BASE  = _get_str("BINANCE_FUTURES_WS_BASE", "wss://fstream.binance.com")
BINANCE_WS_STREAM_SUFFIX = _get_str("BINANCE_WS_STREAM_SUFFIX", "/stream?streams=")

BINANCE_BACKOFF_BASE     = _get_float("BINANCE_BACKOFF_BASE", 0.7)
BINANCE_MAX_RETRIES      = _get_int("BINANCE_MAX_RETRIES", 5)
BINANCE_EXCHANGE_INFO_ON_START = _get_bool("BINANCE_EXCHANGE_INFO_ON_START", False)

BINANCE_RECV_WINDOW      = _get_int("BINANCE_RECV_WINDOW", 10000)
BINANCE_TIME_SYNC_INTERVAL_SEC = _get_int("BINANCE_TIME_SYNC_INTERVAL_SEC", 900)
# ספי time sync (בשימוש utils/binance_client.py)
TIME_SYNC_MAX_RTT_MS           = _get_int("TIME_SYNC_MAX_RTT_MS", 800)
TIME_SYNC_MAX_ABS_OFFSET_MS    = _get_int("TIME_SYNC_MAX_ABS_OFFSET_MS", 1500)

BINANCE_FORCE_HEDGE_MODE       = _get_bool("BINANCE_FORCE_HEDGE_MODE", False)
BINANCE_SKIP_ACCOUNT_MUTATIONS = _get_bool("BINANCE_SKIP_ACCOUNT_MUTATIONS", True)

# בדיקת IP יוצא (אופציונלי)
BINANCE_ALLOWED_EGRESS_IPS = _get_str("BINANCE_ALLOWED_EGRESS_IPS", "")
EGRESS_IP_ENDPOINT         = _get_str("EGRESS_IP_ENDPOINT", "")

# ---------- OpenAI ----------
OPENAI_API_KEY           = _get_str("OPENAI_API_KEY", "")
OPENAI_MODEL             = _get_str("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_BASE_URL          = _get_str("OPENAI_BASE_URL", "")  # ריק → הלקוח ישתמש בברירת המחדל
OPENAI_TIMEOUT_SECONDS   = _get_float("OPENAI_TIMEOUT_SECONDS", 30.0)
OPENAI_MAX_CONCURRENCY   = _get_int("OPENAI_MAX_CONCURRENCY", 4)

# פרמטרים חדשים עבור ai_client (ריטריי/באק-אוף/HTTP2)
OPENAI_MAX_RETRIES       = _get_int("OPENAI_MAX_RETRIES", 3)
OPENAI_BACKOFF_BASE      = _get_float("OPENAI_BACKOFF_BASE", 0.6)
OPENAI_BACKOFF_CAP       = _get_float("OPENAI_BACKOFF_CAP", 10.0)
OPENAI_HTTP2             = _get_bool("OPENAI_HTTP2", False)

# ---------- API Security ----------
API_BEARER_TOKEN         = _get_str("API_BEARER_TOKEN", "secret-token")

# ---------- Auto Trading Controls ----------
ENABLE_AUTO_TRADING      = _get_bool("ENABLE_AUTO_TRADING", False)  # סריקה אוטומטית
EXECUTE_TRADES           = _get_bool("EXECUTE_TRADES", False)       # ביצוע הזמנות בפועל

# ---------- Summaries ----------
def log_config_summary():
    logging.info("[CONFIG] AutoRun=%s Interval=%ss DefaultTF=%s", AUTO_RUN, SCAN_INTERVAL, DEFAULT_INTERVAL)
    logging.info("[CONFIG] Quality≥%s MinVol=%s Top=%s TrendingOnly=%s Concurrency=%s",
                 MIN_QUALITY_SCORE, MIN_VOLUME, TOP_SYMBOLS, TRENDING_ONLY, SCAN_CONCURRENCY)
    logging.info("[CONFIG] PriceMaxAge=%ss StreamsLimit=%s Cooldown=%ss (max %ss)",
                 PRICE_MAX_AGE_SEC, MAX_STREAMS_PER_CONN, REST_COOLDOWN_SEC, REST_MAX_COOLDOWN_SEC)
    logging.info("[CONFIG] Binance Futures=%s Spot=%s WS=%s",
                 BINANCE_FUTURES_HTTP_BASE, BINANCE_SPOT_HTTP_BASE, BINANCE_FUTURES_WS_BASE)
    logging.info("[CONFIG] TimeSync: rtt≤%sms | |offset|≤%sms | every %ss",
                 TIME_SYNC_MAX_RTT_MS, TIME_SYNC_MAX_ABS_OFFSET_MS, BINANCE_TIME_SYNC_INTERVAL_SEC)
    logging.info("[CONFIG] OpenAI model=%s base_url_set=%s timeout=%ss max_conc=%s retries=%s backoff=%.2fs cap=%.1fs http2=%s",
                 OPENAI_MODEL, bool(OPENAI_BASE_URL), OPENAI_TIMEOUT_SECONDS, OPENAI_MAX_CONCURRENCY,
                 OPENAI_MAX_RETRIES, OPENAI_BACKOFF_BASE, OPENAI_BACKOFF_CAP, OPENAI_HTTP2)
    logging.info("[CONFIG] Keys: has_binance=%s has_openai=%s binance_key_prefix=%s",
                 bool(BINANCE_API_KEY), bool(OPENAI_API_KEY), _mask(BINANCE_API_KEY))
    logging.info("[CONFIG] AutoTrading: enable=%s execute=%s", ENABLE_AUTO_TRADING, EXECUTE_TRADES)

def validate_config():
    """
    ולידציה רכה עם אזהרות — לא מפילה את האפליקציה.
    """
    if not BINANCE_API_KEY or not BINANCE_API_SECRET:
        logging.warning("[CONFIG] ⚠️ Binance API keys missing — מצב Public-Only (market data בלבד).")
    if not OPENAI_API_KEY:
        logging.warning("[CONFIG] ⚠️ OPENAI_API_KEY missing — יכול לפגוע ב-AI (ai_analysis).")
    if SCAN_INTERVAL < 15:
        logging.warning("[CONFIG] ⚠️ SCAN_INTERVAL נמוך מ-15s — ייתכן עומס מיותר.")
    if TOP_SYMBOLS > 50:
        logging.warning("[CONFIG] ⚠️ TOP_SYMBOLS גבוה — בוצע clamp ל-50.")
    if SCAN_CONCURRENCY > 20:
        logging.info("[CONFIG] ℹ️ SCAN_CONCURRENCY גבוה — ודא שיש לך משאבים/קצב תעבורה מתאימים.")






