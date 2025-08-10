# utils/config.py
import os

def _b(s: str, default: bool=False) -> bool:
    v = (os.getenv(s, str(default)).strip().lower())
    return v in ("1", "true", "yes", "y", "on")

def _i(s: str, default: int=0) -> int:
    try:
        return int(os.getenv(s, str(default)).strip())
    except Exception:
        return default

def _f(s: str, default: float=0.0) -> float:
    try:
        return float(os.getenv(s, str(default)).strip())
    except Exception:
        return default

def _s(s: str, default: str="") -> str:
    return os.getenv(s, default).strip()

# === כללי ===
AUTO_RUN                 = _b("AUTO_RUN", True)
SCAN_INTERVAL            = _i("SCAN_INTERVAL", 60)
DEFAULT_INTERVAL         = _s("DEFAULT_INTERVAL", "15m")
MIN_QUALITY_SCORE        = _i("MIN_QUALITY_SCORE", 6)
MAX_TRADE_BUDGET         = _f("MAX_TRADE_BUDGET", 100.0)
MIN_VOLUME               = _i("MIN_VOLUME", 1_000_000)
TOP_SYMBOLS              = _i("TOP_SYMBOLS", 30)
TRENDING_ONLY            = _b("TRENDING_ONLY", True)
PORT                     = _i("PORT", 8000)

# === Price guard / WS ===
PRICE_PROTECT_PCT        = _f("PRICE_PROTECT_PCT", 0.25)  # % סטייה מקסימלית
PRICE_MAX_AGE_SEC        = _i("PRICE_MAX_AGE_SEC", 10)

# === Binance ===
BINANCE_API_KEY          = _s("BINANCE_API_KEY")
BINANCE_API_SECRET       = _s("BINANCE_API_SECRET")
BINANCE_SPOT_HTTP_BASE   = _s("BINANCE_SPOT_HTTP_BASE", "https://api.binance.com")
BINANCE_FUTURES_HTTP_BASE= _s("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com")
BINANCE_BACKOFF_BASE     = _f("BINANCE_BACKOFF_BASE", 0.7)
BINANCE_MAX_RETRIES      = _i("BINANCE_MAX_RETRIES", 5)
BINANCE_EXCHANGE_INFO_ON_START = _b("BINANCE_EXCHANGE_INFO_ON_START", False)
BINANCE_RECV_WINDOW      = _i("BINANCE_RECV_WINDOW", 10000)
BINANCE_TIME_SYNC_INTERVAL_SEC = _i("BINANCE_TIME_SYNC_INTERVAL_SEC", 900)

# בקרות רגישות לסביבת ריידיר/אלוליסט
BINANCE_ALLOWED_EGRESS_IPS      = _s("BINANCE_ALLOWED_EGRESS_IPS", "")
EGRESS_IP_ENDPOINT              = _s("EGRESS_IP_ENDPOINT", "")

# מצב חשבון
BINANCE_FORCE_HEDGE_MODE        = (
    True if _s("BINANCE_FORCE_HEDGE_MODE", "").lower() == "true"
    else False if _s("BINANCE_FORCE_HEDGE_MODE", "").lower() == "false"
    else None
)
BINANCE_SKIP_ACCOUNT_MUTATIONS  = _b("BINANCE_SKIP_ACCOUNT_MUTATIONS", False)
MAX_LEVERAGE                    = _i("MAX_LEVERAGE", 35)

# === OpenAI ===
OPENAI_API_KEY           = _s("OPENAI_API_KEY")
OPENAI_MODEL             = _s("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_TIMEOUT_SECONDS   = _f("OPENAI_TIMEOUT_SECONDS", 30.0)
OPENAI_MAX_CONCURRENCY   = _i("OPENAI_MAX_CONCURRENCY", 4)
OPENAI_BASE_URL          = _s("OPENAI_BASE_URL", "")

# === אבטחה / API ===
API_BEARER_TOKEN         = _s("API_BEARER_TOKEN", "secret-token")

def log_config_summary():
    mask = lambda x: (x[:4] + "…") if x and len(x) > 4 else ("*" * len(x))
    print("[CFG] auto_run=", AUTO_RUN,
          "| scan_interval=", SCAN_INTERVAL,
          "| default_interval=", DEFAULT_INTERVAL,
          "| min_quality=", MIN_QUALITY_SCORE,
          "| max_budget=", MAX_TRADE_BUDGET,
          "| ws_max_age=", PRICE_MAX_AGE_SEC,
          "| price_protect%=", PRICE_PROTECT_PCT,
          "| top_symbols=", TOP_SYMBOLS,
          "| trending_only=", TRENDING_ONLY,
          "| binance_keys=", bool(BINANCE_API_KEY), "/", bool(BINANCE_API_SECRET),
          "| binance_key_prefix=", mask(BINANCE_API_KEY),
          "| recvWindow=", BINANCE_RECV_WINDOW,
          "| hedge_mode=", BINANCE_FORCE_HEDGE_MODE,
          "| skip_mutations=", BINANCE_SKIP_ACCOUNT_MUTATIONS)




