from __future__ import annotations
import os, re, logging
from typing import List

def _as_bool(val: str | None, default: bool = False) -> bool:
    if val is None: return default
    return str(val).strip().lower() in {"1","true","yes","on"}

def _as_int(val: str | None, default: int, min_v: int|None=None, max_v: int|None=None) -> int:
    try: x = int(str(val).strip()) if val else default
    except: x = default
    if min_v is not None and x < min_v: x = min_v
    if max_v is not None and x > max_v: x = max_v
    return x

def _as_float(val: str | None, default: float, min_v: float|None=None, max_v: float|None=None) -> float:
    try: x = float(str(val).strip()) if val else default
    except: x = default
    if min_v is not None and x < min_v: x = min_v
    if max_v is not None and x > max_v: x = max_v
    return x

def _csv(val: str|None, default: str="")->List[str]:
    s = val.strip() if (val and isinstance(val,str)) else default.strip()
    if not s: return []
    return [p.strip() for p in s.split(",") if p.strip()]

_SYMBOL_RE = re.compile(r"^[A-Z0-9]{3,20}$")
_INTERVAL_RE = re.compile(r"^(\d+)(m|h|d|w|M|y)$", re.IGNORECASE)

def _norm_symbols(items: List[str]) -> List[str]:
    out, seen = [], set()
    for raw in items:
        s = str(raw).upper().replace(" ","")
        if not s or s in seen: continue
        if not _SYMBOL_RE.match(s):
            logging.warning(f"[CONFIG] Ignoring invalid symbol '{raw}'"); continue
        seen.add(s); out.append(s)
    return out

def _norm_intervals(items: List[str], fallback: List[str]) -> List[str]:
    out=[]
    for it in items:
        if _INTERVAL_RE.match(str(it).strip()):
            out.append(it.strip())
        else: logging.warning(f"[CONFIG] Ignoring invalid interval '{it}'")
    return out or fallback

def _require_url(name,val,must_start:tuple[str,...])->str:
    if not val or not any(val.startswith(p) for p in must_start):
        raise RuntimeError(f"❌ {name} must start with {must_start}, got {val!r}")
    return val.rstrip("/")

APP_ENV=os.getenv("APP_ENV","production").strip().lower()
IS_PROD=APP_ENV=="production"

# Binance
BINANCE_API_KEY=(os.getenv("BINANCE_API_KEY") or "").strip()
BINANCE_API_SECRET=(os.getenv("BINANCE_API_SECRET") or "").strip()
BINANCE_HTTP_BASE=os.getenv("BINANCE_HTTP_BASE","https://api.binance.com").strip()
BINANCE_FUTURES_HTTP_BASE=os.getenv("BINANCE_FUTURES_HTTP_BASE","https://fapi.binance.com").strip()
BINANCE_WS_BASE=os.getenv("BINANCE_WS_BASE","wss://stream.binance.com:9443").strip()
BINANCE_FUTURES_WS_BASE=os.getenv("BINANCE_FUTURES_WS_BASE","wss://fstream.binance.com").strip()
BINANCE_FAPI_ALTS=[b.strip() for b in _csv(os.getenv("BINANCE_FAPI_ALTS"),
    "https://fapi1.binance.com,https://fapi2.binance.com,https://fapi3.binance.com")]

DEFAULT_MARKET=os.getenv("DEFAULT_MARKET","futures").strip().lower()
if DEFAULT_MARKET not in {"spot","futures"}:
    logging.warning(f"[CONFIG] DEFAULT_MARKET invalid {DEFAULT_MARKET}, forcing futures")
    DEFAULT_MARKET="futures"

# Trading
AUTO_RUN=_as_bool(os.getenv("AUTO_RUN"),False)
MIN_LEVERAGE=_as_int(os.getenv("MIN_LEVERAGE"),5,1,125)
MAX_LEVERAGE=_as_int(os.getenv("MAX_LEVERAGE"),35,MIN_LEVERAGE,125)
MAX_TRADE_BUDGET=_as_float(os.getenv("MAX_TRADE_BUDGET"),100,1,1_000_000)
MIN_QUALITY_SCORE=_as_float(os.getenv("MIN_QUALITY_SCORE"),6,0,10)
SCAN_INTERVAL=_as_int(os.getenv("SCAN_INTERVAL"),60,10,3600)
MIN_VOLUME=_as_float(os.getenv("MIN_VOLUME"),1_000_000,0,1e12)
TRENDING_ONLY=_as_bool(os.getenv("TRENDING_ONLY"),False)

# Watchlist
WATCHLIST=_norm_symbols(_csv(os.getenv("WATCHLIST"),"BTCUSDT,ETHUSDT"))
if not WATCHLIST: WATCHLIST=["BTCUSDT","ETHUSDT"]
DEFAULT_ANCHOR="BTCUSDT"
if DEFAULT_ANCHOR not in WATCHLIST: WATCHLIST.insert(0,DEFAULT_ANCHOR)

# Indicators
_raw_intervals=_csv(os.getenv("INDICATOR_INTERVALS"),"15m,1h")
INDICATOR_INTERVALS=_norm_intervals(_raw_intervals,["15m","1h"])
DEFAULT_INTERVAL=INDICATOR_INTERVALS[0] if INDICATOR_INTERVALS else "15m"

# Risk
STOP_LOSS_ATR_MULTIPLIER=_as_float(os.getenv("STOP_LOSS_ATR_MULTIPLIER"),1.5,0.1,10)
USE_TRAILING_SL=_as_bool(os.getenv("USE_TRAILING_SL"),True)

# Options
EXECUTE_TRADES=_as_bool(os.getenv("EXECUTE_TRADES"),False)
BINANCE_SKIP_ACCOUNT_MUTATIONS=_as_bool(os.getenv("BINANCE_SKIP_ACCOUNT_MUTATIONS"),True)
BINANCE_FORCE_HEDGE_MODE=_as_bool(os.getenv("BINANCE_FORCE_HEDGE_MODE"),False)
BINANCE_MARGIN_TYPE_DEFAULT=(os.getenv("BINANCE_MARGIN_TYPE_DEFAULT") or "ISOLATED").strip().upper()
if BINANCE_MARGIN_TYPE_DEFAULT not in {"ISOLATED","CROSSED"}:
    logging.warning(f"[CONFIG] invalid margin {BINANCE_MARGIN_TYPE_DEFAULT}, forcing ISOLATED")
    BINANCE_MARGIN_TYPE_DEFAULT="ISOLATED"

# OpenAI
OPENAI_API_KEY=(os.getenv("OPENAI_API_KEY") or "").strip()
OPENAI_MODEL=(os.getenv("OPENAI_MODEL") or "gpt-4o-mini").strip()
ENABLE_AI_ROUTES=_as_bool(os.getenv("ENABLE_AI_ROUTES"),True)

# Limits
RESPONSE_MAX_BYTES=_as_int(os.getenv("RESPONSE_MAX_BYTES"),2*1024*1024,256*1024,16*1024*1024)

# WS
WS_UPDATE_INTERVAL=_as_int(os.getenv("WS_UPDATE_INTERVAL"),15,5,120)
PRICE_MONITOR_INTERVAL=_as_int(os.getenv("PRICE_MONITOR_INTERVAL"),30,5,300)
PRICE_WS_FRESH_TTL=_as_int(os.getenv("PRICE_WS_FRESH_TTL"),20,5,300)
PRICE_MONITOR_DISABLE=_as_bool(os.getenv("PRICE_MONITOR_DISABLE"),False)

# Logging
LOG_LEVEL=(os.getenv("LOG_LEVEL") or "INFO").strip().upper()
if LOG_LEVEL not in {"CRITICAL","ERROR","WARNING","INFO","DEBUG"}: LOG_LEVEL="INFO"

def _validate_urls():
    _require_url("BINANCE_HTTP_BASE",BINANCE_HTTP_BASE,("https://",))
    _require_url("BINANCE_FUTURES_HTTP_BASE",BINANCE_FUTURES_HTTP_BASE,("https://",))
    _require_url("BINANCE_WS_BASE",BINANCE_WS_BASE,("wss://",))
    _require_url("BINANCE_FUTURES_WS_BASE",BINANCE_FUTURES_WS_BASE,("wss://",))
    for alt in BINANCE_FAPI_ALTS:
        if not alt.startswith("https://"): raise RuntimeError(f"❌ bad alt {alt}")

def _validate_keys():
    if EXECUTE_TRADES and (not BINANCE_API_KEY or not BINANCE_API_SECRET):
        raise RuntimeError("❌ EXECUTE_TRADES=true requires keys")
    if ENABLE_AI_ROUTES and not OPENAI_API_KEY:
        logging.warning("⚠️ ENABLE_AI_ROUTES=true but no OPENAI_API_KEY → AI disabled")

def _validate_semantics():
    if MIN_LEVERAGE>MAX_LEVERAGE: raise RuntimeError("❌ MIN>MAX leverage")
    if not INDICATOR_INTERVALS: raise RuntimeError("❌ No valid intervals")
    if not WATCHLIST: raise RuntimeError("❌ Empty watchlist")

def check_config():
    _validate_urls(); _validate_keys(); _validate_semantics()
    if EXECUTE_TRADES and BINANCE_SKIP_ACCOUNT_MUTATIONS:
        raise RuntimeError("❌ EXECUTE_TRADES=true but skip mutations=true")
    logging.info(f"[CONFIG] Started | EXECUTE_TRADES={EXECUTE_TRADES} | WATCHLIST={WATCHLIST}")
























