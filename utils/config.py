# utils/config.py
"""
Global configuration for AlgoGPT LIVE trading system.
Reads environment variables and exposes them as constants.
"""

import os

# ---------- General ----------
APP_NAME = "AlgoGPT"
APP_ENV = os.getenv("APP_ENV", "production")

# ---------- Binance ----------
# REST
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "").strip()
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "").strip()

# Endpoints (default Binance)
BINANCE_HTTP_BASE = os.getenv("BINANCE_HTTP_BASE", "https://api.binance.com")
BINANCE_FUTURES_HTTP_BASE = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com")
BINANCE_WS_BASE = os.getenv("BINANCE_WS_BASE", "wss://stream.binance.com:9443")
BINANCE_FUTURES_WS_BASE = os.getenv("BINANCE_FUTURES_WS_BASE", "wss://fstream.binance.com")

# Mode: "spot" or "futures"
DEFAULT_MARKET = os.getenv("DEFAULT_MARKET", "futures").lower()

# ---------- Trading Parameters ----------
# Auto execution (live mode)
AUTO_RUN = os.getenv("AUTO_RUN", "false").lower() in ("1", "true", "yes")

# Dynamic leverage range
MIN_LEVERAGE = int(os.getenv("MIN_LEVERAGE", "5"))
MAX_LEVERAGE = int(os.getenv("MAX_LEVERAGE", "35"))

# Default budget per trade (USD)
MAX_TRADE_BUDGET = float(os.getenv("MAX_TRADE_BUDGET", "100"))

# Minimum quality score threshold (0–10)
MIN_QUALITY_SCORE = float(os.getenv("MIN_QUALITY_SCORE", "6"))

# Interval between scans (seconds)
SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL", "60"))

# Volume filter
MIN_VOLUME = float(os.getenv("MIN_VOLUME", "1000000"))
TRENDING_ONLY = os.getenv("TRENDING_ONLY", "false").lower() in ("1", "true", "yes")

# ---------- Indicators ----------
INDICATOR_INTERVALS = os.getenv("INDICATOR_INTERVALS", "15m,1h").split(",")
DEFAULT_INTERVAL = INDICATOR_INTERVALS[0] if INDICATOR_INTERVALS else "15m"

# ---------- Risk Management ----------
STOP_LOSS_ATR_MULTIPLIER = float(os.getenv("STOP_LOSS_ATR_MULTIPLIER", "1.5"))
USE_TRAILING_SL = os.getenv("USE_TRAILING_SL", "true").lower() in ("1", "true", "yes")

# ---------- OpenAI ----------
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").strip()

# ---------- Response Limits ----------
RESPONSE_MAX_BYTES = int(os.getenv("RESPONSE_MAX_BYTES", str(5 * 1024 * 1024)))  # 5 MB

# ---------- Debug ----------
DEBUG = os.getenv("DEBUG", "false").lower() in ("1", "true", "yes")


def check_config() -> None:
    """Run basic config checks"""
    if not BINANCE_API_KEY or not BINANCE_API_SECRET:
        raise RuntimeError("❌ Missing Binance API credentials!")
    if not OPENAI_API_KEY:
        raise RuntimeError("❌ Missing OpenAI API Key!")



















