# utils/config.py
# מקור אמת אחיד לכל ההגדרות. קורא מ-OS (Render) ורק משלים מ-.env בלוקאל (לא דורס).
import os
import logging
from dotenv import load_dotenv

# בלוקאל ימלא חסרים מ-.env; בענן (Render) לא ישפיע.
load_dotenv(override=False)

# ---------- Helpers ----------
def _env_bool(key: str, default: bool = False) -> bool:
    v = os.environ.get(key, str(default)).strip().lower()
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

def _env_list_csv(key: str, default: str = "*") -> list[str]:
    raw = os.environ.get(key, default).strip()
    if raw == "*":
        return ["*"]
    return [x.strip() for x in raw.split(",") if x.strip()]

def _mask(s: str, keep: int = 4) -> str:
    if not s:
        return ""
    s = str(s)
    if len(s) <= keep:
        return "*" * len(s)
    return s[:keep] + "…" + "*" * max(0, len(s) - keep - 1)

# ---------- Binance / Networking ----------
BINANCE_API_KEY = os.environ.get("BINANCE_API_KEY", "").strip()
BINANCE_API_SECRET = os.environ.get("BINANCE_API_SECRET", "").strip()
BINANCE_EXCHANGE_INFO_ON_START = _env_bool("BINANCE_EXCHANGE_INFO_ON_START", False)
BINANCE_BACKOFF_BASE = _env_float("BINANCE_BACKOFF_BASE", 0.7)
BINANCE_MAX_RETRIES = _env_int("BINANCE_MAX_RETRIES", 5)

# ---------- OpenAI ----------
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini").strip()
OPENAI_FALLBACK_MODEL = os.environ.get("OPENAI_FALLBACK_MODEL", "").strip()  # אופציונלי
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "").strip()             # אופציונלי (Azure/Proxy)
OPENAI_TIMEOUT_SECONDS = _env_float("OPENAI_TIMEOUT_SECONDS", 30.0)
OPENAI_MAX_CONCURRENCY = _env_int("OPENAI_MAX_CONCURRENCY", 4)

# ---------- Trading / Executor ----------
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

# ---------- Server / API ----------
PORT = _env_int("PORT", int(os.environ.get("PORT", "8000")))
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").strip().upper()
API_BEARER_TOKEN = os.environ.get("API_BEARER_TOKEN", "secret-token").strip()
CORS_ALLOW_ORIGINS = _env_list_csv("CORS_ALLOW_ORIGINS", "*")  # "*" או CSV של דומיינים

# ---------- Logging Summary ----------
def log_config_summary():
    logging.info(
        "[config] BINANCE: EXCHANGE_INFO_ON_START=%s | BACKOFF_BASE=%.2f | MAX_RETRIES=%d",
        BINANCE_EXCHANGE_INFO_ON_START, BINANCE_BACKOFF_BASE, BINANCE_MAX_RETRIES
    )
    logging.info(
        "[config] EXECUTOR: AUTO_RUN=%s | SCAN_INTERVAL=%d | MIN_QUALITY_SCORE=%d | MAX_TRADE_BUDGET=%.2f",
        AUTO_RUN, SCAN_INTERVAL, MIN_QUALITY_SCORE, MAX_TRADE_BUDGET
    )
    logging.info(
        "[config] OPENAI: MODEL=%s | TIMEOUT=%.1fs | MAX_CONCURRENCY=%d | BASE_URL=%s | FALLBACK=%s",
        OPENAI_MODEL, OPENAI_TIMEOUT_SECONDS, OPENAI_MAX_CONCURRENCY,
        (OPENAI_BASE_URL or "default"), (OPENAI_FALLBACK_MODEL or "none")
    )
    logging.info(
        "[config] SERVER: PORT=%d | LOG_LEVEL=%s | CORS_ALLOW_ORIGINS=%s",
        PORT, LOG_LEVEL, ",".join(CORS_ALLOW_ORIGINS)
    )
    if BINANCE_API_KEY:
        logging.info("[config] Binance key prefix=%s", _mask(BINANCE_API_KEY, keep=4))
    if OPENAI_API_KEY:
        logging.info("[config] OpenAI key prefix=%s", _mask(OPENAI_API_KEY, keep=4))

# ---------- Safe snapshot (ללא סודות) ----------
def as_dict() -> dict:
    return {
        # Binance
        "binance_exchange_info_on_start": bool(BINANCE_EXCHANGE_INFO_ON_START),
        "binance_backoff_base": float(BINANCE_BACKOFF_BASE),
        "binance_max_retries": int(BINANCE_MAX_RETRIES),
        "has_binance_key": bool(bool(BINANCE_API_KEY)),
        "binance_key_prefix": _mask(BINANCE_API_KEY),
        # OpenAI
        "openai_model": OPENAI_MODEL,
        "openai_fallback_model": OPENAI_FALLBACK_MODEL or "",
        "openai_timeout_seconds": float(OPENAI_TIMEOUT_SECONDS),
        "openai_max_concurrency": int(OPENAI_MAX_CONCURRENCY),
        "openai_base_url_set": bool(bool(OPENAI_BASE_URL)),
        "has_openai_key": bool(bool(OPENAI_API_KEY)),
        # Trading
        "auto_run": bool(AUTO_RUN),
        "scan_interval": int(SCAN_INTERVAL),
        "min_quality_score": int(MIN_QUALITY_SCORE),
        "max_trade_budget": float(MAX_TRADE_BUDGET),
        "default_interval": DEFAULT_INTERVAL,
        "min_volume": int(MIN_VOLUME),
        "top_symbols": int(TOP_SYMBOLS),
        "trending_only": bool(TRENDING_ONLY),
        "price_protect_pct": float(PRICE_PROTECT_PCT),
        "price_max_age_sec": int(PRICE_MAX_AGE_SEC),
        # Server/API
        "port": int(PORT),
        "log_level": LOG_LEVEL,
        "cors_allow_origins": CORS_ALLOW_ORIGINS,
        "has_api_bearer_token": bool(bool(API_BEARER_TOKEN)),
    }

__all__ = [
    # helpers
    "log_config_summary", "as_dict",
    # binance
    "BINANCE_API_KEY", "BINANCE_API_SECRET", "BINANCE_EXCHANGE_INFO_ON_START",
    "BINANCE_BACKOFF_BASE", "BINANCE_MAX_RETRIES",
    # openai
    "OPENAI_API_KEY", "OPENAI_MODEL", "OPENAI_FALLBACK_MODEL", "OPENAI_BASE_URL",
    "OPENAI_TIMEOUT_SECONDS", "OPENAI_MAX_CONCURRENCY",
    # trading
    "AUTO_RUN", "SCAN_INTERVAL", "MIN_QUALITY_SCORE", "MAX_TRADE_BUDGET",
    "DEFAULT_INTERVAL", "MIN_VOLUME", "TOP_SYMBOLS", "TRENDING_ONLY",
    "PRICE_PROTECT_PCT", "PRICE_MAX_AGE_SEC",
    # server/api
    "PORT", "LOG_LEVEL", "API_BEARER_TOKEN", "CORS_ALLOW_ORIGINS",
]


