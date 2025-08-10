# utils/config.py
# מקור אמת אחיד לכל ההגדרות. קורא מ-OS (Render) ורק משלים מ-.env בלוקאל (לא דורס).
import os
import logging
from dotenv import load_dotenv

# אל תדרוס משתני OS: בלוקאל ימלא חסרים מ-.env, בענן לא ישפיע.
load_dotenv(override=False)

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

# === OpenAI ===
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini").strip()

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

# === Server ===
# Render מספק PORT ב-OS; בלוקאל תוכל להגדיר ב-.env אם תרצה.
PORT = _env_int("PORT", int(os.environ.get("PORT", "8000")))

def log_config_summary():
    logging.info(
        "[config] BINANCE_EXCHANGE_INFO_ON_START=%s | BACKOFF_BASE=%.2f | MAX_RETRIES=%d | "
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
