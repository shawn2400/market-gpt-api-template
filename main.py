# main.py
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

# === אוטו-אקזקיוטר ===
from auto_executor import start_executor, stop_executor, is_executor_running

# ---------- לוגים ----------
logging.basicConfig(level=getattr(logging, config.LOG_LEVEL, logging.INFO),
                    format='[%(asctime)s] %(levelname)s: %(message)s')
config.log_config_summary()

# ---------- אבטחה ----------
API_TOKEN = config.API_BEARER_TOKEN
bearer_scheme = HTTPBearer()

def verify_token(credentials: HTTPAuthorizationCredentials = Security(bearer_scheme)):
    if credentials.credentials != API_TOKEN:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return True

# ---------- אפליקציה ----------
APP_VERSION = "2.2.0"
app = FastAPI(title="AlgoGPT API", version=APP_VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ALLOW_ORIGINS,
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
    # Binance ping (עם ריטריי פנימי)
    ping_and_info()

    # WebSocket למחירים חיים
    symbols = _pick_ws_symbols()
    await launch_multi_websocket(symbols)
    logging.info(f"[startup] WS launched for {len(symbols)} symbols")

    # Auto Executor לפי ENV
    if config.AUTO_RUN:
        started = start_executor()
        logging.info(f"[AUTO] Auto Executor started: {started}")

@app.on_event("shutdown")
async def _on_shutdown():
    try:
        if is_executor_running():
            stop_executor()
    except Exception as e:
        logging.warning(f"[shutdown] stop_executor failed: {e}")

# ---------- ראוטים ----------
@app.get("/", tags=["Config"])
async def root_status():
    return {
        "status": "ok",
        "version": APP_VERSION,
        "auto_run": bool(config.AUTO_RUN),
        "scan_interval": int(config.SCAN_INTERVAL),
        "min_quality": int(config.MIN_QUALITY_SCORE),
        "port": int(config.PORT),
    }

@app.get("/health", tags=["Config"])
async def health():
    return {"ok": True, "version": APP_VERSION}

@app.get("/config", tags=["Config"], dependencies=[Depends(verify_token)])
async def get_config():
    return config.as_dict()  # ללא סודות

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
        if not live or not is_price_fresh(symbol, max_age_sec=config.PRICE_MAX_AGE_SEC):
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
    uvicorn.run(app, host="0.0.0.0", port=int(config.PORT))























