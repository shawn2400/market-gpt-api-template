# main.py
import os
import logging
from typing import Optional, List

from fastapi import FastAPI, Depends, HTTPException, Security, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# === קונפיג מרכזי (קורא ENV ומסכם לוג) ===
from utils import config

# === מודולים פונקציונליים ===
from utils.ai_analysis import analyze_with_ai, predict_optimal_sl_tp
from utils.multi_tf_scanner import multi_tf_scan_with_ai
from utils.trade_executor import execute_trade_live
from utils.watchlist_utils import load_watchlist
from utils.ws_fallback import get_price, is_price_fresh, launch_multi_websocket
from utils.trending_utils import get_trending_symbols
from utils.binance_client import ping_and_info

# === AI health (SDK) ===
from utils.ai_client import ai_healthcheck

# ננסה להביא גם בדיקת HTTP ישירה אם קיימת (לא חובה)
try:
    from utils.ai_health import ping_openai
except Exception:
    ping_openai = None  # בדיקת HTTP ישירה אופציונלית

# === אוטו-אקזקיוטר ===
from auto_executor import start_executor, stop_executor, is_executor_running

# ---------- לוגים ----------
_LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, _LOG_LEVEL, logging.INFO),
    format='[%(asctime)s] %(levelname)s: %(message)s'
)
config.log_config_summary()

# ---------- אבטחה ----------
# אם ב-config אין API_BEARER_TOKEN, נשתמש ב-ENV או default.
API_TOKEN = getattr(config, "API_BEARER_TOKEN", os.getenv("API_BEARER_TOKEN", "secret-token"))
bearer_scheme = HTTPBearer()

def verify_token(credentials: HTTPAuthorizationCredentials = Security(bearer_scheme)):
    if credentials.credentials != API_TOKEN:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return True

# ---------- CORS ----------
# תמיכה ב-ENV: CORS_ALLOW_ORIGINS="https://a.com,https://b.com" | ברירת מחדל: "*"
_cors_env = os.getenv("CORS_ALLOW_ORIGINS", "*")
if _cors_env.strip() == "*":
    _allow_origins = ["*"]
else:
    _allow_origins = [o.strip() for o in _cors_env.split(",") if o.strip()]

# ---------- אפליקציה ----------
APP_VERSION = "2.3.1"
app = FastAPI(title="AlgoGPT API", version=APP_VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- מודלים ----------
class TradeRequest(BaseModel):
    symbol: str
    side: str                     # "LONG" / "SHORT"
    entry: Optional[float] = None # אם חסר – ניקח מלייב
    sl: Optional[float] = None    # אם חסר – נחשב
    tp: Optional[float] = None    # אם חסר – נחשב
    budget: Optional[float] = 100
    leverage: Optional[int] = 10

# ---------- עזר: בחירת סמלים ל-WS ----------
def _pick_ws_symbols() -> List[str]:
    try:
        wl = load_watchlist(min_quality=config.MIN_QUALITY_SCORE) or []
        syms = [x["symbol"] for x in wl if isinstance(x, dict) and x.get("symbol")]
        if not syms:
            syms = get_trending_symbols(source="binance24h", market="futures",
                                        top_n=min(30, config.TOP_SYMBOLS))
        if not syms:
            syms = ["BTCUSDT", "ETHUSDT", "BNBUSDT"]
        out, seen = [], set()
        for s in syms:
            u = str(s).upper()
            if u and u not in seen:
                seen.add(u); out.append(u)
        return out[:min(40, config.TOP_SYMBOLS)]
    except Exception as e:
        logging.warning(f"[startup] WS symbol pick failed: {e}")
        return ["BTCUSDT", "ETHUSDT", "BNBUSDT"]

# ---------- אירועי חיים ----------
@app.on_event("startup")
async def _on_startup():
    try:
        # Binance ping (עם ריטריי פנימי)
        ping_and_info()
    except Exception as e:
        logging.warning(f"[startup] ping_and_info failed: {e}")

    # WebSocket למחירים חיים
    try:
        symbols = _pick_ws_symbols()
        await launch_multi_websocket(symbols)
        logging.info(f"[startup] WS launched for {len(symbols)} symbols")
    except Exception as e:
        logging.warning(f"[startup] launch_multi_websocket failed: {e}")

    # Auto Executor לפי ENV
    try:
        if config.AUTO_RUN:
            started = start_executor()
            logging.info(f"[AUTO] Auto Executor started: {started}")
    except Exception as e:
        logging.warning(f"[startup] start_executor failed: {e}")

@app.on_event("shutdown")
async def _on_shutdown():
    try:
        if is_executor_running():
            stop_executor()
    except Exception as e:
        logging.warning(f"[shutdown] stop_executor failed: {e}")

# ---------- עזר: צילום קונפיג ללא סודות ----------
def _config_snapshot() -> dict:
    def _mask(s: str, keep: int = 4) -> str:
        if not s:
            return ""
        s = str(s)
        return s[:keep] + "…" if len(s) > keep else "*" * len(s)

    snap = {
        "version": APP_VERSION,
        "auto_run": bool(getattr(config, "AUTO_RUN", True)),
        "scan_interval": int(getattr(config, "SCAN_INTERVAL", 60)),
        "min_quality_score": int(getattr(config, "MIN_QUALITY_SCORE", 6)),
        "max_trade_budget": float(getattr(config, "MAX_TRADE_BUDGET", 100.0)),
        "default_interval": str(getattr(config, "DEFAULT_INTERVAL", "15m")),
        "min_volume": int(getattr(config, "MIN_VOLUME", 1_000_000)),
        "top_symbols": int(getattr(config, "TOP_SYMBOLS", 30)),
        "trending_only": bool(getattr(config, "TRENDING_ONLY", True)),
        "price_protect_pct": float(getattr(config, "PRICE_PROTECT_PCT", 0.10)),
        "price_max_age_sec": int(getattr(config, "PRICE_MAX_AGE_SEC", 10)),
        "port": int(getattr(config, "PORT", int(os.environ.get("PORT", "8000")))),
        "openai_model": str(getattr(config, "OPENAI_MODEL", "gpt-4o-mini")),
        "openai_timeout_seconds": float(getattr(config, "OPENAI_TIMEOUT_SECONDS", 30.0)),
        "openai_max_concurrency": int(getattr(config, "OPENAI_MAX_CONCURRENCY", 4)),
        "openai_base_url_set": bool(bool(getattr(config, "OPENAI_BASE_URL", ""))),
        "binance_exchange_info_on_start": bool(getattr(config, "BINANCE_EXCHANGE_INFO_ON_START", False)),
        "binance_backoff_base": float(getattr(config, "BINANCE_BACKOFF_BASE", 0.7)),
        "binance_max_retries": int(getattr(config, "BINANCE_MAX_RETRIES", 5)),
        # חיווי לא חושף סודות:
        "has_openai_key": bool(bool(getattr(config, "OPENAI_API_KEY", ""))),
        "has_binance_key": bool(bool(getattr(config, "BINANCE_API_KEY", ""))),
        "binance_key_prefix": _mask(getattr(config, "BINANCE_API_KEY", "")),
    }
    return snap

# ---------- ראוטים ----------
@app.get("/", tags=["Config"])
async def root_status():
    return {
        "status": "ok",
        "version": APP_VERSION,
        "auto_run": bool(getattr(config, "AUTO_RUN", True)),
        "scan_interval": int(getattr(config, "SCAN_INTERVAL", 60)),
        "min_quality": int(getattr(config, "MIN_QUALITY_SCORE", 6)),
        "port": int(getattr(config, "PORT", int(os.environ.get("PORT", "8000")))),
    }

@app.get("/health", tags=["Config"])
async def health():
    return {"ok": True, "version": APP_VERSION}

@app.get("/ai/health", tags=["Config"])
async def ai_health():
    """
    בדיקת חיבור ולטנסי ל-GPT:
    - sdk: דרך ה-SDK (utils.ai_client)
    - http: בדיקת HTTP ישירה אם זמינה (utils.ai_health.ping_openai)
    אם ה-SDK נכשל → נחזיר 503 (כדי שתוכל לנטר); אחרת 200.
    """
    sdk = await ai_healthcheck()
    http = None
    if callable(ping_openai):
        try:
            http = await ping_openai(timeout_sec=6)
        except Exception as e:
            http = {"ok": False, "error": f"http_probe_failed: {e}"}

    payload = {"sdk": sdk, "http": http}
    if not sdk.get("ok"):
        # חשוב: לזרוק, לא להחזיר אובייקט של HTTPException
        raise HTTPException(status_code=503, detail=payload)
    return payload

@app.get("/config", tags=["Config"], dependencies=[Depends(verify_token)])
async def get_config():
    return _config_snapshot()  # ללא סודות

@app.get("/auto/status", tags=["Auto"], dependencies=[Depends(verify_token)])
def auto_status():
    return {"running": is_executor_running()}

@app.post("/auto/start", tags=["Auto"], dependencies=[Depends(verify_token)])
def auto_start():
    return {"started": start_executor()}

@app.post("/auto/stop", tags=["Auto"], dependencies=[Depends(verify_token)])
def auto_stop():
    return {"stopped": stop_executor()}

@app.post("/trade", tags=["Trades"], dependencies=[Depends(verify_token)])
async def place_trade(trade: TradeRequest):
    """
    כניסה ממוכנת:
    - אם entry חסר → ניקח מחיר חי מ־WS (אם לא זמין/לא עדכני → 503)
    - אם SL/TP חסרים → predict_optimal_sl_tp (עם פולבק דטרמיניסטי בפנים)
    - שאר ההגנות (Price Protect, וכו׳) נעשות בתוך execute_trade_live
    """
    symbol = trade.symbol.upper().strip()
    direction = trade.side.upper().strip()

    # קבלת מחיר לייב אם לא נשלח
    entry = trade.entry
    if entry is None:
        live = await get_price(symbol)
        if not live or not is_price_fresh(symbol, max_age_sec=getattr(config, "PRICE_MAX_AGE_SEC", 10)):
            raise HTTPException(status_code=503, detail=f"Live price unavailable or stale for {symbol}")
        entry = float(live)

    sl, tp = trade.sl, trade.tp
    if sl is None or tp is None:
        try:
            sl, tp = await predict_optimal_sl_tp(symbol, direction, entry_price=entry)
        except Exception as e:
            logging.warning(f"[trade] predict_optimal_sl_tp failed: {e}")
            # execute_trade_live יפיל אם חסר

    result = await execute_trade_live(
        symbol=symbol,
        direction=direction,
        entry=entry,
        stop=sl,
        tp=tp,
        leverage=int(trade.leverage or 10),
        budget_usd=float(trade.budget or 100),
        market_type="futures",
    )
    return result

@app.get("/scan/multi", tags=["Trades"], dependencies=[Depends(verify_token)])
async def scan_multi(
    interval: str = "15m,1h",
    min_quality: int = 6,
    top: int = 10,
    market_type: str = "futures",
    trending_only: bool = False,
    trending_source: str = "coingecko",
):
    timeframes = tuple([x.strip() for x in interval.split(",") if x.strip()]) or ("15m", "1h")
    results = await multi_tf_scan_with_ai(
        timeframes=timeframes,
        markets=(market_type,),
        min_quality=min_quality,
        top=top,
        trending_only=trending_only,
        trending_source=trending_source,
    )
    return {"results": results}

# הרצה לוקאלית (ב-Render לא רלוונטי; שם gunicorn/uvicorn worker מריץ)
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(getattr(config, "PORT", int(os.environ.get("PORT", "8000")))))

























