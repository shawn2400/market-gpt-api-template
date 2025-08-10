# utils/config.py
# מקור אמת אחיד לכל ההגדרות. קורא מ-OS (Render) ורק משלים מ-.env בלוקאל (לא דורס).
import os
import logging
from dotenv import load_dotenv

# בלוקאל ימלא חסרים מ-.env; בענן (Render) ערכי OS נשארים שליטים.
load_dotenv(override=False)

# ---------------------------
# Helpers
# ---------------------------
def _env_bool(key: str, default: bool = False) -> bool:
    v = os.environ.get(key, None)
    if v is None:
        return bool(default)
    v = str(v).strip().lower()
    return v in ("1", "true", "yes", "on")

def _env_int(key: str, default: int) -> int:
    v = os.environ.get(key, None)
    if v is None or str(v).strip() == "":
        return int(default)
    try:
        return int(str(v).strip())
    except Exception:
        return int(default)

def _env_float(key: str, default: float) -> float:
    v = os.environ.get(key, None)
    if v is None or str(v).strip() == "":
        return float(default)
    try:
        return float(str(v).strip())
    except Exception:
        return float(default)

def _env_csv(key: str, default: str = "") -> list[str]:
    v = os.environ.get(key, default)
    if not v:
        return []
    return [x.strip() for x in str(v).split(",") if x.strip()]

def _mask(s: str, keep: int = 4) -> str:
    if not s:
        return ""
    s = str(s)
    if len(s) <= keep:
        return "*" * len(s)
    return s[:keep] + "…" + "*" * max(0, len(s) - keep - 1)

# ---------------------------
# Binance / Networking
# ---------------------------
BINANCE_API_KEY = os.environ.get("BINANCE_API_KEY", "").strip()
BINANCE_API_SECRET = os.environ.get("BINANCE_API_SECRET", "").strip()
BINANCE_EXCHANGE_INFO_ON_START = _env_bool("BINANCE_EXCHANGE_INFO_ON_START", False)
BINANCE_BACKOFF_BASE = _env_float("BINANCE_BACKOFF_BASE", 0.7)
BINANCE_MAX_RETRIES = _env_int("BINANCE_MAX_RETRIES", 5)

# Hedge mode (אם עובדים עם פוזישן כפול LONG/SHORT)
BINANCE_HEDGE_MODE = _env_bool("BINANCE_HEDGE_MODE", False)

# אופציונלי: קונפיג ל-WS/HTTP (לא חובה לשנות)
BINANCE_FUTURES_HTTP_BASE = os.environ.get("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com").strip()
BINANCE_SPOT_HTTP_BASE = os.environ.get("BINANCE_SPOT_HTTP_BASE", "https://api.binance.com").strip()
BINANCE_FUTURES_WS_BASE = os.environ.get("BINANCE_FUTURES_WS_BASE", "wss://fstream.binance.com").strip()

# ---------------------------
# OpenAI
# ---------------------------
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini").strip()

# ---------------------------
# Trading / Executor
# ---------------------------
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

# ---------------------------
# Server / API
# ---------------------------
# Render מספק PORT ב־OS; בלוקאל ברירת־מחדל 5000
PORT = _env_int("PORT", int(os.environ.get("PORT", "5000")))
API_BEARER_TOKEN = os.environ.get("API_BEARER_TOKEN", "secret-token").strip()

# CORS
CORS_ALLOW_ORIGINS = _env_csv("CORS_ALLOW_ORIGINS", "*")
# אם הוגדר "*" – נתעלם מרשימה ספציפית
if CORS_ALLOW_ORIGINS == ["*"] or CORS_ALLOW_ORIGINS == []:
    CORS_ALLOW_ORIGINS = ["*"]

# ---------------------------
# Logging level (אופציונלי)
# ---------------------------
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").strip().upper()
if LOG_LEVEL not in ("CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"):
    LOG_LEVEL = "INFO"

def log_config_summary():
    logging.info(
        "[config] EXCHANGE_INFO_ON_START=%s | BACKOFF_BASE=%.2f | MAX_RETRIES=%d | "
        "AUTO_RUN=%s | SCAN_INTERVAL=%d | MIN_QUALITY=%d | MAX_TRADE_BUDGET=%.2f | "
        "PRICE_PROTECT_PCT=%.4f | PRICE_MAX_AGE=%ds | OPENAI_MODEL=%s | PORT=%d | HEDGE_MODE=%s",
        BINANCE_EXCHANGE_INFO_ON_START,
        BINANCE_BACKOFF_BASE,
        BINANCE_MAX_RETRIES,
        AUTO_RUN,
        SCAN_INTERVAL,
        MIN_QUALITY_SCORE,
        MAX_TRADE_BUDGET,
        PRICE_PROTECT_PCT,
        PRICE_MAX_AGE_SEC,
        OPENAI_MODEL,
        PORT,
        BINANCE_HEDGE_MODE,
    )
    if BINANCE_API_KEY:
        logging.info("[config] Binance key prefix=%s", _mask(BINANCE_API_KEY, keep=4))
    if OPENAI_API_KEY:
        logging.info("[config] OpenAI key prefix=%s", _mask(OPENAI_API_KEY, keep=4))
    logging.info("[config] CORS_ALLOW_ORIGINS=%s", CORS_ALLOW_ORIGINS)

def as_dict() -> dict:
    """נוח לדיבוג/סטטוס."""
    return {
        "BINANCE_EXCHANGE_INFO_ON_START": BINANCE_EXCHANGE_INFO_ON_START,
        "BINANCE_BACKOFF_BASE": BINANCE_BACKOFF_BASE,
        "BINANCE_MAX_RETRIES": BINANCE_MAX_RETRIES,
        "BINANCE_HEDGE_MODE": BINANCE_HEDGE_MODE,
        "AUTO_RUN": AUTO_RUN,
        "SCAN_INTERVAL": SCAN_INTERVAL,
        "MIN_QUALITY_SCORE": MIN_QUALITY_SCORE,
        "MAX_TRADE_BUDGET": MAX_TRADE_BUDGET,
        "DEFAULT_INTERVAL": DEFAULT_INTERVAL,
        "MIN_VOLUME": MIN_VOLUME,
        "TOP_SYMBOLS": TOP_SYMBOLS,
        "TRENDING_ONLY": TRENDING_ONLY,
        "PRICE_PROTECT_PCT": PRICE_PROTECT_PCT,
        "PRICE_MAX_AGE_SEC": PRICE_MAX_AGE_SEC,
        "PORT": PORT,
        "OPENAI_MODEL": OPENAI_MODEL,
        "CORS_ALLOW_ORIGINS": CORS_ALLOW_ORIGINS,
        "BINANCE_FUTURES_HTTP_BASE": BINANCE_FUTURES_HTTP_BASE,
        "BINANCE_SPOT_HTTP_BASE": BINANCE_SPOT_HTTP_BASE,
        "BINANCE_FUTURES_WS_BASE": BINANCE_FUTURES_WS_BASE,
        # לא מחזירים מפתחות גולמיים
    }

__all__ = [
    # Binance
    "BINANCE_API_KEY", "BINANCE_API_SECRET",
    "BINANCE_EXCHANGE_INFO_ON_START", "BINANCE_BACKOFF_BASE", "BINANCE_MAX_RETRIES",
    "BINANCE_HEDGE_MODE",
    "BINANCE_FUTURES_HTTP_BASE", "BINANCE_SPOT_HTTP_BASE", "BINANCE_FUTURES_WS_BASE",
    # OpenAI
    "OPENAI_API_KEY", "OPENAI_MODEL",
    # Trading/Executor
    "AUTO_RUN", "SCAN_INTERVAL", "MIN_QUALITY_SCORE", "MAX_TRADE_BUDGET",
    "DEFAULT_INTERVAL", "MIN_VOLUME", "TOP_SYMBOLS", "TRENDING_ONLY",
    "PRICE_PROTECT_PCT", "PRICE_MAX_AGE_SEC",
    # Server/API
    "PORT", "API_BEARER_TOKEN", "CORS_ALLOW_ORIGINS",
    # Utils
    "LOG_LEVEL", "log_config_summary", "as_dict",
]
