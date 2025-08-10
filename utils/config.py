# utils/config.py
# מקור אמת אחיד לכל ההגדרות. קורא מ-OS (Render) ורק משלים מ-.env בלוקאל (לא דורס).
import os
import json
import logging
from dotenv import load_dotenv

# אל תדרוס משתני OS: בלוקאל ימלא חסרים מ-.env, בענן לא ישפיע.
load_dotenv(override=False)

def _env_bool(key: str, default: bool = False) -> bool:
    v = str(os.environ.get(key, str(default))).strip().lower()
    return v in ("1", "true", "yes", "on")

def _env_int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, str(default)))
    except Exception:
        return int(default)

def _env_float(key: str, default: float) -> float:
    try:
        return float(os.environ.get(key, str(default)))
    except Exception:
        return float(default)

def _env_list(key: str, default):
    raw = os.environ.get(key)
    if not raw:
        return default
    try:
        # תומך גם ב־JSON וגם בפורמט מופרד בפסיקים
        if raw.strip().startswith("["):
            return json.loads(raw)
        return [x.strip() for x in raw.split(",") if x.strip()]
    except Exception:
        return default

def _mask(s: str, keep: int = 4) -> str:
    if not s:
        return ""
    s = str(s)
    if len(s) <= keep:
        return "*" * len(s)
    return s[:keep] + "…" + "*" * max(0, len(s) - keep - 1)

# === Binance / Networking ===
BINANCE_API_KEY = os.environ.get("BINANCE_API_KEY", "").strip()
BINANCE_API_SECRET = os.environ.get("BINANCE_API_SECRET", "").strip()
BINANCE_EXCHANGE_INFO_ON_START = _env_bool("BINANCE_EXCHANGE_INFO_ON_START", False)
BINANCE_BACKOFF_BASE = _env_float("BINANCE_BACKOFF_BASE", 0.7)
BINANCE_MAX_RETRIES = _env_int("BINANCE_MAX_RETRIES", 5)

# כתובות HTTP/WS ברירת מחדל
BINANCE_FUTURES_HTTP_BASE = os.environ.get("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com").strip()
BINANCE_SPOT_HTTP_BASE    = os.environ.get("BINANCE_SPOT_HTTP_BASE", "https://api.binance.com").strip()

BINANCE_FUTURES_WS_BASE   = os.environ.get("BINANCE_FUTURES_WS_BASE", "wss://fstream.binance.com").strip()
BINANCE_SPOT_WS_BASE      = os.environ.get("BINANCE_SPOT_WS_BASE", "wss://stream.binance.com:9443").strip()
# שני השירותים משתמשים באותו סיומת מולטיסטרים
BINANCE_WS_STREAM_SUFFIX  = os.environ.get("BINANCE_WS_STREAM_SUFFIX", "/stream?streams=").strip()

# === OpenAI ===
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
OPENAI_MODEL   = os.environ.get("OPENAI_MODEL", "gpt-4o-mini").strip()
OPENAI_TIMEOUT_SECONDS  = _env_float("OPENAI_TIMEOUT_SECONDS", 30.0)
OPENAI_MAX_CONCURRENCY  = _env_int("OPENAI_MAX_CONCURRENCY", 4)
OPENAI_BASE_URL         = os.environ.get("OPENAI_BASE_URL", "").strip() or None

# === Trading / Executor ===
AUTO_RUN = _env_bool("AUTO_RUN", True)
SCAN_INTERVAL = _env_int("SCAN_INTERVAL", 60)
MIN_QUALITY_SCORE = _env_int("MIN_QUALITY_SCORE", 6)
MAX_TRADE_BUDGET = _env_float("MAX_TRADE_BUDGET", 100.0)
DEFAULT_INTERVAL = os.environ.get("DEFAULT_INTERVAL", "15m").strip()
MIN_VOLUME = _env_int("MIN_VOLUME", 1_000_000)
TOP_SYMBOLS = _env_int("TOP_SYMBOLS", 30)
TRENDING_ONLY = _env_bool("TRENDING_ONLY", True)

PRICE_PROTECT_PCT = _env_float("PRICE_PROTECT_PCT", 0.10)
PRICE_MAX_AGE_SEC = _env_int("PRICE_MAX_AGE_SEC", 10)

# === Server / Security ===
PORT = _env_int("PORT", int(os.environ.get("PORT", "8000")))
API_BEARER_TOKEN = os.environ.get("API_BEARER_TOKEN", "secret-token").strip()
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
CORS_ALLOW_ORIGINS = _env_list("CORS_ALLOW_ORIGINS", ["*"])

def log_config_summary():
    logging.info(
        "[config] EX_INFO_ON_START=%s | BACKOFF_BASE=%.2f | MAX_RETRIES=%d | "
        "SCAN_INTERVAL=%d | MIN_QUALITY_SCORE=%d | MAX_TRADE_BUDGET=%.2f | MODEL=%s | PORT=%d",
        BINANCE_EXCHANGE_INFO_ON_START,
        BINANCE_BACKOFF_BASE,
        BINANCE_MAX_RETRIES,
        SCAN_INTERVAL,
        MIN_QUALITY_SCORE,
        MAX_TRADE_BUDGET,
        OPENAI_MODEL,
        PORT,
    )
    if BINANCE_API_KEY:
        logging.info("[config] Binance key prefix=%s", _mask(BINANCE_API_KEY, keep=4))
    if OPENAI_API_KEY:
        logging.info("[config] OpenAI key prefix=%s", _mask(OPENAI_API_KEY, keep=4))
    logging.info(
        "[config] WS bases: futures=%s | spot=%s | suffix=%s",
        BINANCE_FUTURES_WS_BASE, BINANCE_SPOT_WS_BASE, BINANCE_WS_STREAM_SUFFIX
    )

def as_dict():
    """קונפיג 'ציבורי' ללא סודות, עבור /config."""
    return {
        "auto_run": AUTO_RUN,
        "scan_interval": SCAN_INTERVAL,
        "min_quality_score": MIN_QUALITY_SCORE,
        "max_trade_budget": MAX_TRADE_BUDGET,
        "default_interval": DEFAULT_INTERVAL,
        "min_volume": MIN_VOLUME,
        "top_symbols": TOP_SYMBOLS,
        "trending_only": TRENDING_ONLY,
        "price_protect_pct": PRICE_PROTECT_PCT,
        "price_max_age_sec": PRICE_MAX_AGE_SEC,
        "port": PORT,
        "log_level": LOG_LEVEL,
        "openai_model": OPENAI_MODEL,
        "openai_timeout_seconds": OPENAI_TIMEOUT_SECONDS,
        "openai_max_concurrency": OPENAI_MAX_CONCURRENCY,
        "openai_base_url_custom": bool(OPENAI_BASE_URL),
        "binance_futures_http_base": BINANCE_FUTURES_HTTP_BASE,
        "binance_spot_http_base": BINANCE_SPOT_HTTP_BASE,
        "binance_futures_ws_base": BINANCE_FUTURES_WS_BASE,
        "binance_spot_ws_base": BINANCE_SPOT_WS_BASE,
        "binance_ws_stream_suffix": BINANCE_WS_STREAM_SUFFIX,
        "cors_allow_origins": CORS_ALLOW_ORIGINS,
    }




