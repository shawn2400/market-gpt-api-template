# main.py (גרסה מתוקנת – /scan/multi פתוח, שאר הראוטים מאובטחים + operation_id לכל ראוט)

import os
import logging
import asyncio
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, Depends, HTTPException, Security, status, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# === קונפיג ===
from utils import config

# === מודולים ===
from utils.ai_analysis import analyze_with_ai, predict_optimal_sl_tp
from utils.multi_tf_scanner import multi_tf_scan_with_ai
from utils.trade_executor import execute_trade_live
from utils.ws_fallback import get_price_smart
from utils.binance_client import (
    ping_and_info, futures_exchange_info_safe, futures_mark_price, get_client, sync_server_time
)
from utils.ai_client import ai_healthcheck  # noqa: F401 (להמשך)
from utils.pnl_tracker import generate_pnl_pdf

# === אופציונלי ===
try:
    from utils.ai_client import ai_client  # type: ignore  # noqa: F401
except Exception:
    ai_client = None
try:
    from utils.ai_health import ping_openai  # type: ignore  # noqa: F401
except Exception:
    ping_openai = None

from auto_executor import start_executor, stop_executor, is_executor_running

# ---------- לוגים ----------
_LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, _LOG_LEVEL, logging.INFO),
    format='[%(asctime)s] %(levelname)s: %(message)s',
    force=True
)
try:
    config.log_config_summary()
except Exception:
    pass

# ---------- אבטחה ----------
API_TOKEN = getattr(config, "API_BEARER_TOKEN", os.getenv("API_BEARER_TOKEN", "secret-token"))
bearer_scheme = HTTPBearer()

def verify_token(credentials: HTTPAuthorizationCredentials = Security(bearer_scheme)):
    if credentials.credentials != API_TOKEN:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return True

# ---------- אפליקציה ----------
APP_VERSION = "2.12.1"
app = FastAPI(title="AlgoGPT API", version=APP_VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"]
)

# ---------- Routers נלווים (גריד) ----------
try:
    from routes.grid import router as grid_router
    app.include_router(grid_router)
except Exception as e:
    logging.warning("[INIT] grid router not loaded: %s", e)

# ---------- מודלים ----------
class TradeRequest(BaseModel):
    symbol: str = Field(..., example="BTCUSDT")
    side: str = Field(..., pattern="^(LONG|SHORT)$")
    entry: Optional[float] = Field(None, description="אם None — יילקח מחיר שוק")
    sl: Optional[float] = None
    tp: Optional[float] = None
    budget: Optional[float] = Field(100, gt=0)
    leverage: Optional[int] = Field(10, ge=1, le=125)

class TradeResponse(BaseModel):
    status: str
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

class AiAnalyzeRequest(BaseModel):
    symbol: str
    rsi: float
    adx: float
    trend: str
    pattern: str
    volume: float

class SLTPRequest(BaseModel):
    symbol: str
    direction: str = Field(..., pattern="^(LONG|SHORT)$")
    entry: float
    atr: Optional[float] = None

# ---------- בריאות בסיסית ----------
@app.get(
    "/",
    tags=["Config"],
    operation_id="checkServerStatus",
)
async def root():
    return {"status": "ok", "version": APP_VERSION}

# ---------- סריקת שוק – פתוח ללא אימות ----------
@app.get(
    "/scan/multi",
    tags=["Trades"],
    operation_id="scanMulti",
)
async def scan_multi(
    interval: str = "15m,1h",
    min_quality: int = 6,
    top: int = 10,
    market_type: str = "futures",
    trending_only: Optional[bool] = Query(None, description="אם None - יילקח מהקונפיג"),
    trending_source: str = "coingecko",
):
    """
    סריקה עם Multi-TF + ניתוח AI (פתוח ללא אימות).
    """
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

# ---------- /trade ----------
@app.post(
    "/trade",
    tags=["Trades"],
    dependencies=[Depends(verify_token)],
    operation_id="placeTrade",
)
async def place_trade(req: TradeRequest) -> TradeResponse:
    """
    מבצע טרייד חי (כפוף לדגלי EXECUTE_TRADES / BINANCE_SKIP_ACCOUNT_MUTATIONS).
    """
    try:
        # אם אין SL/TP — נחשב אוטומטית עם AI+פולבק
        sl, tp = req.sl, req.tp
        if sl is None or tp is None:
            live = await get_price_smart(req.symbol)
            entry_for_sltp = float(req.entry) if req.entry is not None else float(live or 0.0)
            if entry_for_sltp <= 0:
                return TradeResponse(status="error", error="live/entry price unavailable")
            sl, tp = await predict_optimal_sl_tp(
                symbol=req.symbol, direction=req.side, entry_price=entry_for_sltp, atr=None
            )

        resp = await execute_trade_live(
            symbol=req.symbol,
            entry=req.entry,   # אם None — בפונקציית הביצוע יילקח מחיר חי
            stop=sl,
            tp=tp,
            direction=req.side,
            leverage=int(req.leverage or 10),
            budget_usd=float(req.budget or 100),
            market_type="futures"
        )
        if resp.get("status") == "success":
            return TradeResponse(status="success", result=resp)
        return TradeResponse(status="error", error=resp.get("error", "trade failed"))
    except Exception as e:
        logging.error("[/trade] %s", e, exc_info=True)
        return TradeResponse(status="error", error=str(e))

# ---------- /ai-analyze ----------
@app.post(
    "/ai-analyze",
    tags=["AI"],
    dependencies=[Depends(verify_token)],
    operation_id="aiAnalyze",
)
async def ai_analyze(req: AiAnalyzeRequest):
    """
    ניתוח AI על סמך אינדיקטורים שסופקו (ממפה ל־analyze_with_ai ע״י יצירת מסגרת אחת).
    """
    try:
        tf_item = {
            "symbol": req.symbol,
            "interval": "custom",
            "market": "futures",
            "frames": ["custom"],
            "quality_score": 0.0,
            "trend": req.trend,
            "direction": "LONG" if str(req.trend).upper() in ("UP", "LONG", "BUY") else "SHORT",
            "rsi": float(req.rsi),
            "adx": float(req.adx),
            "volume": float(req.volume),
            "indicators": {
                "rsi": float(req.rsi),
                "adx": float(req.adx),
                "atr": 0.0,
                "macd": 0.0,
                "macd_signal": 0.0,
                "macd_hist": 0.0,
                "ema_21": 0.0,
                "ema_50": 0.0,
                "vwap": 0.0,
                "volume": float(req.volume),
                "volume_mean": max(1.0, float(req.volume)),
                "pattern": req.pattern or "unknown",
            },
        }
        out = await analyze_with_ai([tf_item])
        return out
    except Exception as e:
        logging.error("[/ai-analyze] %s", e, exc_info=True)
        return {"error": str(e)}

# ---------- /sltp ----------
@app.post(
    "/sltp",
    tags=["Trades"],
    dependencies=[Depends(verify_token)],
    operation_id="suggestSLTP",
)
async def suggest_sltp(req: SLTPRequest):
    try:
        sl, tp = await predict_optimal_sl_tp(
            symbol=req.symbol, direction=req.direction, entry_price=req.entry, atr=req.atr
        )
        return {"symbol": req.symbol, "direction": req.direction, "sl": sl, "tp": tp}
    except Exception as e:
        logging.error("[/sltp] %s", e, exc_info=True)
        raise HTTPException(status_code=400, detail=str(e))

# ---------- /price ----------
@app.get(
    "/price",
    tags=["Trades"],
    dependencies=[Depends(verify_token)],
    operation_id="getPrice",
)
async def get_price(symbol: str):
    p = await get_price_smart(symbol)
    if p is None:
        raise HTTPException(status_code=400, detail="price unavailable")
    return {"symbol": symbol.upper(), "price": float(p)}

# ---------- Executor ----------
@app.get(
    "/executor/start",
    tags=["Executor"],
    dependencies=[Depends(verify_token)],
    operation_id="startExecutor",
)
async def executor_start():
    start_executor()
    return {"started": True, "running": is_executor_running()}

@app.get(
    "/executor/stop",
    tags=["Executor"],
    dependencies=[Depends(verify_token)],
    operation_id="stopExecutor",
)
async def executor_stop():
    stop_executor()
    return {"stopped": True, "running": is_executor_running()}

@app.get(
    "/executor/status",
    tags=["Executor"],
    dependencies=[Depends(verify_token)],
    operation_id="executorStatus",
)
async def executor_status():
    return {"running": is_executor_running()}

# ---------- דו״ח PnL ----------
@app.get(
    "/report/pnl/pdf",
    tags=["Reports"],
    dependencies=[Depends(verify_token)],
    operation_id="generatePnlPdf",
)
async def report_pnl_pdf():
    path = generate_pnl_pdf()
    if not path:
        raise HTTPException(status_code=404, detail="no PnL data")
    return {"path": path}

# ---------- Debug Binance ----------
@app.get(
    "/debug/binance-futures",
    tags=["Debug"],
    dependencies=[Depends(verify_token)],
    operation_id="debugBinanceFutures",
)
async def debug_binance_futures(symbol: str = "BTCUSDT", place_test: bool = True):
    ok_ping = False
    try:
        ok_ping = bool(ping_and_info())
    except Exception:
        ok_ping = False
    try:
        sync_server_time()
    except Exception:
        pass
    try:
        prem = futures_mark_price(symbol)
    except Exception as e:
        prem = {"error": str(e)}
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

# ---------- הפעלה מקומית ----------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))






































