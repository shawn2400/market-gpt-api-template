# main.py (גרסה מתוקנת – מאפשרת /scan/multi גם ללא אימות)

import os
import logging
import asyncio
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, Depends, HTTPException, Security, status, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# === קונפיג ===
from utils import config

# === מודולים ===
from utils.ai_analysis import analyze_with_ai, predict_optimal_sl_tp
from utils.multi_tf_scanner import multi_tf_scan_with_ai
from utils.trade_executor import execute_trade_live
from utils.watchlist_utils import load_watchlist
from utils.ws_fallback import (
    get_price as get_price_cached, get_price_smart, is_price_fresh, launch_multi_websocket
)
from utils.trending_utils import get_trending_symbols
from utils.binance_client import (
    ping_and_info, futures_exchange_info_safe, futures_mark_price, get_client, sync_server_time
)
from utils.ai_client import ai_healthcheck

# === אופציונלי ===
try: from utils.ai_client import ai_client  # type: ignore
except: ai_client = None
try: from utils.ai_health import ping_openai
except: ping_openai = None
from auto_executor import start_executor, stop_executor, is_executor_running

# ---------- לוגים ----------
_LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, _LOG_LEVEL, logging.INFO), format='[%(asctime)s] %(levelname)s: %(message)s', force=True)
try: config.log_config_summary()
except: pass

# ---------- אבטחה ----------
API_TOKEN = getattr(config, "API_BEARER_TOKEN", os.getenv("API_BEARER_TOKEN", "secret-token"))
bearer_scheme = HTTPBearer()

def verify_token(credentials: HTTPAuthorizationCredentials = Security(bearer_scheme)):
    if credentials.credentials != API_TOKEN:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return True

# ---------- אפליקציה ----------
APP_VERSION = "2.9.4"
app = FastAPI(title="AlgoGPT API", version=APP_VERSION)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

WS_SYMBOLS: List[str] = []

# ---------- מודלים ----------
class TradeRequest(BaseModel):
    symbol: str
    side: str
    entry: Optional[float] = None
    sl: Optional[float] = None
    tp: Optional[float] = None
    budget: Optional[float] = 100
    leverage: Optional[int] = 10

class _TradeResult(BaseModel):
    status: str
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

# ---------- סריקת שוק – נפתח ללא אימות ----------
@app.get("/scan/multi", tags=["Trades"])
async def scan_multi(
    interval: str = "15m,1h",
    min_quality: int = 6,
    top: int = 10,
    market_type: str = "futures",
    trending_only: bool = Query(None),
    trending_source: str = "coingecko",
):
    timeframes = tuple([x.strip() for x in interval.split(",") if x.strip()]) or ("15m", "1h")
    if trending_only is None:
        trending_only = bool(getattr(config, "TRENDING_ONLY", True))

    results = await multi_tf_scan_with_ai(
        timeframes=timeframes,
        markets=(market_type,),
        min_quality=min_quality,
        top=top,
        trending_only=trending_only,
        trending_source=trending_source,
    )
    return {"results": results}

# ---------- המשך ראוטים: רק עם אימות ----------
@app.get("/config", dependencies=[Depends(verify_token)])
async def get_config():
    return {"status": "ok", "version": APP_VERSION, "api_key_prefix": API_TOKEN[:4] + "…"}

@app.get("/debug/binance-futures", dependencies=[Depends(verify_token)])
async def debug_binance_futures(symbol: str = "BTCUSDT", place_test: bool = True):
    ok_ping = False
    try: ok_ping = bool(ping_and_info())
    except: ok_ping = False
    try: sync_server_time()
    except: pass
    try: prem = futures_mark_price(symbol)
    except Exception as e: prem = {"error": str(e)}
    try:
        ex_info = await asyncio.to_thread(futures_exchange_info_safe)
        sym_count = len(ex_info.get("symbols", [])) if isinstance(ex_info, dict) else None
    except Exception as e:
        ex_info, sym_count = {"error": str(e)}, None

    test_err = None
    if place_test:
        try:
            client = get_client()
            await asyncio.to_thread(
                client.futures_create_test_order,
                symbol=symbol, side="BUY", type="LIMIT", timeInForce="GTC",
                quantity="0.001", price="1000"
            )
        except Exception as e:
            test_err = str(e)

    return {
        "ping_ok": ok_ping,
        "mark_price": prem,
        "symbols_count": sym_count,
        "test_order_ok": place_test and test_err is None,
        "test_order_error": test_err,
    }

# --- ניתן להוסיף עוד ראוטים עם Depends(verify_token) בהתאם ---

# ---------- הפעלה ----------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)




































