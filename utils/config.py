"""
Global configuration for AlgoGPT LIVE trading system.
Reads environment variables, normalizes them, and exposes validated constants.
Raises RuntimeError on critical misconfigurations in production.
"""

from __future__ import annotations
import os
import re
import logging
from typing import List

# ------------------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------------------
def _as_bool(val: str | None, default: bool = False) -> bool:
    if val is None:
        return default
    return str(val).strip().lower() in {"1", "true", "yes", "on"}

def _as_int(val: str | None, default: int, min_v: int | None = None, max_v: int | None = None) -> int:
    try:
        x = int(str(val).strip()) if val is not None else default
    except Exception:
        x = default
    if min_v is not None and x < min_v:
        x = min_v
    if max_v is not None and x > max_v:
        x = max_v
    return x

def _as_float(val: str | None, default: float, min_v: float | None = None, max_v: float | None = None) -> float:
    try:
        x = float(str(val).strip()) if val is not None else default
    except Exception:
        x = default
    if min_v is not None and x < min_v:
        x = min_v
    if max_v is not None and x > max_v:
        x = max_v
    return x

def _csv(val: str | None, default: str = "") -> List[str]:
    s = val.strip() if (val and isinstance(val, str)) else default.strip()
    if not s:
        return []
    return [p.strip() for p in s.split(",") if p.strip()]

_SYMBOL_RE = re.compile(r"^[A-Z0-9]{3,20}$")  # e.g., BTCUSDT / ETHUSDT
_INTERVAL_RE = re.compile(r"^(\d+)(m|h|d|w|M|y)$", re.IGNORECASE)  # 1m, 15m, 1h, 4h, 1d...

def _norm_symbols(items: List[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for raw in items:
        s = str(raw).upper().replace(" ", "")
        if not s or s in seen:
            continue
        if not _SYMBOL_RE.match(s):
            logging.warning(f"[CONFIG] Ignoring invalid symbol '{raw}'")
            continue
        seen.add(s)
        out.append(s)
    return out

def _norm_intervals(items: List[str], fallback: List[str]) -> List[str]:
    out: List[str] = []
    for it in items:
        t = str(it).strip()
        if _INTERVAL_RE.match(t):
            out.append(t)
        else:
            logging.warning(f"[CONFIG] Ignoring invalid interval '{it}'")
    return out or fallback

def _require_url(name: str, val: str, must_start: tuple[str, ...]) -> str:
    if not val or not any(val.startswith(p) for p in must_start):
        raise RuntimeError(f"❌ {name} must start with one of {must_start}, got: {val!r}")
    return val.rstrip("/")

# ------------------------------------------------------------------------------
# General
# ------------------------------------------------------------------------------
APP_NAME = "AlgoGPT"
APP_ENV = os.getenv("APP_ENV", "production").strip().lower()   # production / dev / test
IS_PROD = APP_ENV == "production"

# ------------------------------------------------------------------------------
# Binance (HTTP/WS bases)
# ------------------------------------------------------------------------------
BINANCE_API_KEY = (os.getenv("BINANCE_API_KEY") or "").strip()
BINANCE_API_SECRET = (os.getenv("BINANCE_API_SECRET") or "").strip()

BINANCE_HTTP_BASE = (os.getenv("BINANCE_HTTP_BASE") or "https://api.binance.com").strip()
BINANCE_FUTURES_HTTP_BASE = (os.getenv("BINANCE_FUTURES_HTTP_BASE") or "https://fapi.binance.com").strip()
BINANCE_WS_BASE = (os.getenv("BINANCE_WS_BASE") or "wss://stream.binance.com:9443").strip()
BINANCE_FUTURES_WS_BASE = (os.getenv("BINANCE_FUTURES_WS_BASE") or "wss://fstream.binance.com").strip()

# Optional alternates (used על ידי לקוח ה־HTTP לחילופים/חסימות)
BINANCE_FAPI_ALTS = [
    base.strip()
    for base in _csv(os.getenv("BINANCE_FAPI_ALTS"), "https://fapi1.binance.com,https://fapi2.binance.com,https://fapi3.binance.com")
]

# Mode: "spot" or "futures"
DEFAULT_MARKET = os.getenv("DEFAULT_MARKET", "futures").strip().lower()
if DEFAULT_MARKET not in {"spot", "futures"}:
    logging.warning(f"[CONFIG] DEFAULT_MARKET invalid '{DEFAULT_MARKET}', forcing 'futures'")
    DEFAULT_MARKET = "futures"

# ------------------------------------------------------------------------------
# Trading Parameters
# ------------------------------------------------------------------------------
AUTO_RUN = _as_bool(os.getenv("AUTO_RUN"), False)

MIN_LEVERAGE = _as_int(os.getenv("MIN_LEVERAGE"), 5, 1, 125)
MAX_LEVERAGE = _as_int(os.getenv("MAX_LEVERAGE"), 35, MIN_LEVERAGE, 125)

MAX_TRADE_BUDGET = _as_float(os.getenv("MAX_TRADE_BUDGET"), 100.0, 1.0, 1_000_000.0)
MIN_QUALITY_SCORE = _as_float(os.getenv("MIN_QUALITY_SCORE"), 6.0, 0.0, 10.0)
SCAN_INTERVAL = _as_int(os.getenv("SCAN_INTERVAL"), 60, 10, 3600)

MIN_VOLUME = _as_float(os.getenv("MIN_VOLUME"), 1_000_000.0, 0.0, 1e12)
TRENDING_ONLY = _as_bool(os.getenv("TRENDING_ONLY"), False)

# ------------------------------------------------------------------------------
# Watchlist
# ------------------------------------------------------------------------------
WATCHLIST = _norm_symbols(_csv(os.getenv("WATCHLIST"), "BTCUSDT,ETHUSDT"))
if not WATCHLIST:
    WATCHLIST = ["BTCUSDT", "ETHUSDT"]
DEFAULT_ANCHOR = "BTCUSDT"
if DEFAULT_ANCHOR not in WATCHLIST:
    WATCHLIST.insert(0, DEFAULT_ANCHOR)

# ------------------------------------------------------------------------------
# Indicators
# ------------------------------------------------------------------------------
_raw_intervals = _csv(os.getenv("INDICATOR_INTERVALS"), "15m,1h")
INDICATOR_INTERVALS = _norm_intervals(_raw_intervals, ["15m", "1h"])
DEFAULT_INTERVAL = INDICATOR_INTERVALS[0] if INDICATOR_INTERVALS else "15m"

# ------------------------------------------------------------------------------
# Risk Management
# ------------------------------------------------------------------------------
STOP_LOSS_ATR_MULTIPLIER = _as_float(os.getenv("STOP_LOSS_ATR_MULTIPLIER"), 1.5, 0.1, 10.0)
USE_TRAILING_SL = _as_bool(os.getenv("USE_TRAILING_SL"), True)

# ------------------------------------------------------------------------------
# Extra Binance Options
# ------------------------------------------------------------------------------
EXECUTE_TRADES = _as_bool(os.getenv("EXECUTE_TRADES"), False)
BINANCE_SKIP_ACCOUNT_MUTATIONS = _as_bool(os.getenv("BINANCE_SKIP_ACCOUNT_MUTATIONS"), True)
BINANCE_FORCE_HEDGE_MODE = _as_bool(os.getenv("BINANCE_FORCE_HEDGE_MODE"), False)
BINANCE_MARGIN_TYPE_DEFAULT = (os.getenv("BINANCE_MARGIN_TYPE_DEFAULT") or "ISOLATED").strip().upper()
if BINANCE_MARGIN_TYPE_DEFAULT not in {"ISOLATED", "CROSSED"}:
    logging.warning(f"[CONFIG] BINANCE_MARGIN_TYPE_DEFAULT invalid '{BINANCE_MARGIN_TYPE_DEFAULT}', forcing 'ISOLATED'")
    BINANCE_MARGIN_TYPE_DEFAULT = "ISOLATED"

# ------------------------------------------------------------------------------
# OpenAI
# ------------------------------------------------------------------------------
OPENAI_API_KEY = (os.getenv("OPENAI_API_KEY") or "").strip()
OPENAI_MODEL = (os.getenv("OPENAI_MODEL") or "gpt-4o-mini").strip()
OPENAI_BASE_URL = (os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1").strip()

# ------------------------------------------------------------------------------
# Response Limits
# ------------------------------------------------------------------------------
RESPONSE_MAX_BYTES = _as_int(os.getenv("RESPONSE_MAX_BYTES"), 2 * 1024 * 1024, 256 * 1024, 16 * 1024 * 1024)

# ------------------------------------------------------------------------------
# WS / Price Monitor (תואם main.py ו-ws_fallback)
# ------------------------------------------------------------------------------
WS_UPDATE_INTERVAL = _as_int(os.getenv("WS_UPDATE_INTERVAL"), 15, 5, 120)
PRICE_MONITOR_INTERVAL = _as_int(os.getenv("PRICE_MONITOR_INTERVAL"), 30, 5, 300)
PRICE_WS_FRESH_TTL = _as_int(os.getenv("PRICE_WS_FRESH_TTL"), 20, 5, 300)
PRICE_MONITOR_DISABLE = _as_bool(os.getenv("PRICE_MONITOR_DISABLE"), False)

# ------------------------------------------------------------------------------
# Debug / Logging
# ------------------------------------------------------------------------------
DEBUG = _as_bool(os.getenv("DEBUG"), False)
LOG_LEVEL = (os.getenv("LOG_LEVEL") or "INFO").strip().upper()
if LOG_LEVEL not in {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}:
    LOG_LEVEL = "INFO"

# ------------------------------------------------------------------------------
# Validation / Checks
# ------------------------------------------------------------------------------
def dump_config_sanitized() -> dict:
    """Return a sanitized snapshot of config (no secrets) for safe logging."""
    return {
        "app_env": APP_ENV,
        "default_market": DEFAULT_MARKET,
        "watchlist": WATCHLIST,
        "indicator_intervals": INDICATOR_INTERVALS,
        "default_interval": DEFAULT_INTERVAL,
        "auto_run": AUTO_RUN,
        "min_leverage": MIN_LEVERAGE,
        "max_leverage": MAX_LEVERAGE,
        "max_trade_budget": MAX_TRADE_BUDGET,
        "min_quality_score": MIN_QUALITY_SCORE,
        "scan_interval": SCAN_INTERVAL,
        "min_volume": MIN_VOLUME,
        "trending_only": TRENDING_ONLY,
        "sl_atr_multiplier": STOP_LOSS_ATR_MULTIPLIER,
        "use_trailing_sl": USE_TRAILING_SL,
        "exec_trades": EXECUTE_TRADES,
        "skip_account_mutations": BINANCE_SKIP_ACCOUNT_MUTATIONS,
        "force_hedge_mode": BINANCE_FORCE_HEDGE_MODE,
        "margin_type_default": BINANCE_MARGIN_TYPE_DEFAULT,
        "openai_model": OPENAI_MODEL,
        "response_max_bytes": RESPONSE_MAX_BYTES,
        "ws_update_interval": WS_UPDATE_INTERVAL,
        "price_monitor_interval": PRICE_MONITOR_INTERVAL,
        "price_ws_fresh_ttl": PRICE_WS_FRESH_TTL,
        "price_monitor_disable": PRICE_MONITOR_DISABLE,
        "http_bases": {
            "spot": BINANCE_HTTP_BASE,
            "futures": BINANCE_FUTURES_HTTP_BASE,
            "alts": BINANCE_FAPI_ALTS,
        },
        "ws_bases": {
            "spot": BINANCE_WS_BASE,
            "futures": BINANCE_FUTURES_WS_BASE,
        },
        "log_level": LOG_LEVEL,
        "debug": DEBUG,
    }

def _validate_urls() -> None:
    # HTTP bases
    _require_url("BINANCE_HTTP_BASE", BINANCE_HTTP_BASE, ("https://",))
    _require_url("BINANCE_FUTURES_HTTP_BASE", BINANCE_FUTURES_HTTP_BASE, ("https://",))
    # WS bases
    _require_url("BINANCE_WS_BASE", BINANCE_WS_BASE, ("wss://",))
    _require_url("BINANCE_FUTURES_WS_BASE", BINANCE_FUTURES_WS_BASE, ("wss://",))
    # alternates
    for alt in BINANCE_FAPI_ALTS:
        if not alt.startswith("https://"):
            raise RuntimeError(f"❌ BINANCE_FAPI_ALTS contains non-https base: {alt}")

def _validate_keys() -> None:
    # Binance keys:
    if EXECUTE_TRADES:
        # למסחר חי חובה מפתחות!
        if not BINANCE_API_KEY or not BINANCE_API_SECRET:
            raise RuntimeError("❌ EXECUTE_TRADES=true requires BINANCE_API_KEY and BINANCE_API_SECRET")
    else:
        # ללא מסחר חי — ב־prod עדיין נרצה מפתחות לרוב (שליפות מצב/מגבלות, וכו׳)
        if IS_PROD and (not BINANCE_API_KEY or not BINANCE_API_SECRET):
            logging.warning("⚠️ Production without Binance credentials. Some features may be limited.")

    # OpenAI:
    if IS_PROD and not OPENAI_API_KEY:
        raise RuntimeError("❌ Missing OpenAI API Key in production")

def _validate_semantics() -> None:
    # מינוף
    if MIN_LEVERAGE > MAX_LEVERAGE:
        raise RuntimeError(f"❌ MIN_LEVERAGE({MIN_LEVERAGE}) > MAX_LEVERAGE({MAX_LEVERAGE})")

    # Intervals
    if not INDICATOR_INTERVALS:
        raise RuntimeError("❌ No valid INDICATOR_INTERVALS supplied")

    # Watchlist
    if not WATCHLIST:
        raise RuntimeError("❌ Empty WATCHLIST after normalization")

    # Margin type & market
    if DEFAULT_MARKET == "futures" and BINANCE_MARGIN_TYPE_DEFAULT not in {"ISOLATED", "CROSSED"}:
        raise RuntimeError("❌ Invalid BINANCE_MARGIN_TYPE_DEFAULT for futures")

def check_config() -> None:
    """
    Run all validations. In production, raises on failures.
    In dev/test, logs warnings for some issues.
    """
    try:
        _validate_urls()
        _validate_keys()
        _validate_semantics()
    except Exception as e:
        if IS_PROD:
            raise
        logging.warning(f"[CONFIG] Non-fatal in {APP_ENV}: {e}")

    # חריגה לוגית: אם פקודות מסחר מופעלות אבל שינויים בחשבון חסומים
    if EXECUTE_TRADES and BINANCE_SKIP_ACCOUNT_MUTATIONS:
        raise RuntimeError("❌ EXECUTE_TRADES=true but BINANCE_SKIP_ACCOUNT_MUTATIONS=true → No trades will be executed!")

    logging.info(f"[CONFIG] AlgoGPT started in {APP_ENV} | EXECUTE_TRADES={EXECUTE_TRADES} | WATCHLIST={WATCHLIST}")
    logging.debug({"config": dump_config_sanitized()})






















