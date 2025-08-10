# main.py
import os
import logging
from typing import Optional, Tuple, List

from fastapi import FastAPI, Depends, HTTPException, Security, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# --- מערכת ---
from dotenv import load_dotenv
load_dotenv()

# --- קונפיג מרכזי ---
from utils import config  # ודא שקובץ utils/config.py קיים ומקריא ENV

# --- מודולים פונקציונליים ---
from utils.ai_analysis import analyze_with_ai, predict_optimal_sl_tp
from utils.multi_tf_scanner import multi_tf_scan_with_ai
from utils.trade_executor import execute_trade_live
from utils.watchlist_utils import load_watchlist
from utils.ws_fallback import get_price, is_price_fresh
from utils.ws_fallback import launch_multi_websocket
from utils.trending_utils import get_trending_symbols
from utils.binance_client import ping_and_info  # מריץ ping ב-import/Startup

# --- אוטו-אקזקיוטר ---
from auto_executor import start_executor, stop_executor, is_executor_running

# ========= לוגים =========
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s: %(message)s')

# ========= אבטחה =========
API_TOKEN = os.getenv("API_BEARER_TOKEN", "secret-token")  # קבע ב-Render
bearer_scheme = HTTPBearer()

def verify_token(credentials: HTTPAuthorizationCredentials = Security(bearer_scheme)):
    if credentials.credentials != API_TOKEN:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return True

# ========= אפליקציה =========
APP_VERSION = "2.1.0"
app = FastAPI(title="AlgoGPT API", version=APP_VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ========= מודלים =========
class TradeRequest(BaseModel):
    symbol: str
    side: str                     # "LONG" / "SHORT"
    entry: Optional[float] = None # אם חסר – ניקח מלייב
    sl: Optional[float] = None    # אם חסר – נחשב
    tp: Optional[float] = None    # אם חסר – נחשב
    budget: Optional[float] = 100
    leverage: Optional[int] = 10

# ========= עזר פנימי =========
def _pick_ws_symbols() -> List[str]:
    """
    בוחר סמלים ל־WS: קודם מה-Watchlist, אחרת Trending, אחרת fallback.
    מגביל לכמות סבירה כדי לשמור על יעילות WS.
    """
    try:
        wl = load_watchlist(min_quality=getattr(config, "MIN_QUALITY_SCORE", 6)) or []
        syms = [x["symbol"] for x in wl if isinstance(x, dict) and x.get("symbol")]
        if not syms:
            syms = get_trending_symbols(source="binance24h", market="futures", top_n=min(30, getattr(config, "TOP_SYMBOLS", 30)))
        if not syms:
            syms = ["BTCUSDT", "ETHUSDT", "BNBUSDT"]
        # סינון כפילויות ושמירה על אותיות גדולות
        seen, out = set(), []
        for s in syms:
            u = str(s).upper()
            if u and u not in seen:
                seen.add(u); out.append(u)
        return out[:min(40, getattr(config, "TOP_SYMBOLS", 30))]
    except Exception as e:
        logging.warning(f"[startup] WS symbol pick failed: {e}")
        return ["BTCUSDT", "ETHUSDT", "BNBUSDT"]

async def _ensure_ws_started():
    try:
        symbols = _pick_ws_symbols()
        await launch_multi_websocket(symbols)
        logging.info(f"[startup] WS launched for {len(symbols)} symbols")
    except Exception as e:
        logging.error(f"[startup] WS launch failed: {e}")

# ========= אירועי חיים =========
@app.on_event("startup")
async def _on_startup():
    # חיבור Binance (ping + אופציונלי exchange info לפי הקונפיג)
    ping_and_info()

    # הפעלת WS
    await _ensure_ws_started()

    # הפעלת האוטו-אקזקיוטר אוטומטית לפי ENV
    if bool(getattr(config, "AUTO_RUN", False)):
        started = start_executor()
        logging.info(f"[AUTO] Auto Executor started: {started}")

@app.on_event("shutdown")
async def _on_shutdown():
    try:
        if is_executor_running():
            stop_executor()
    except Exception as e:
        logging.warning(f"[shutdown] stop_executor failed: {e}")

# ========= ראוטים =========
@app.get("/", tags=["Config"])
async def root_status():
    return {
        "status": "ok",
        "version": APP_VERSION,
        "auto_run": bool(getattr(config, "AUTO_RUN", False)),
        "scan_interval": int(getattr(config, "SCAN_INTERVAL", 60)),
        "min_quality": int(getattr(config, "MIN_QUALITY_SCORE", 6)),
    }

@app.get("/health", tags=["Config"])
async def health():
    return {"ok": True, "version": APP_VERSION}

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
    - אם entry חסר → ניקח מחיר חי מ־WS (אם לא זמין, נחזיר שגיאה)
    - אם SL/TP חסרים → נחשב בעזרת predict_optimal_sl_tp (עם פולבק דטרמיניסטי)
    - Price Protect וכל הבדיקות נעשות בתוך execute_trade_live
    """
    symbol = trade.symbol.upper().strip()
    direction = trade.side.upper().strip()
    entry = trade.entry

    # Entry חי אם חסר
    if entry is None:
        live = await get_price(symbol)
        if not live or not is_price_fresh(symbol, max_age_sec=int(getattr(config, "PRICE_MAX_AGE_SEC", 10))):
            raise HTTPException(status_code=503, detail=f"Live price unavailable or stale for {symbol}")
        entry = float(live)

    # SL/TP חכמים אם חסרים
    sl, tp = trade.sl, trade.tp
    if sl is None or tp is None:
        try:
            sl, tp = await predict_optimal_sl_tp(symbol, direction, entry_price=entry)
        except Exception as e:
            logging.warning(f"[trade] predict_optimal_sl_tp failed, will let executor fallback: {e}")
            sl = sl or None
            tp = tp or None

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
    timeframes = tuple([x.strip() for x in interval.split(",") if x.strip()])
    if not timeframes:
        timeframes = ("15m", "1h")

    results = await multi_tf_scan_with_ai(
        timeframes=timeframes,
        markets=(market_type,),
        min_quality=min_quality,
        top=top,
        trending_only=trending_only,
        trending_source=trending_source,
    )
    return {"results": results}

# (ניתן להוסיף מסלולים נוספים לפי הצורך)

# הרצה לוקאלית (לא בשימוש ב-Render שמריץ gunicorn/uvicorn worker)
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "5000")))






















