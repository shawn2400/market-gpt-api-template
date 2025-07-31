# main.py

import os
import time
import uvicorn
import asyncio
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from dotenv import load_dotenv
from utils.ai_analysis import analyze_with_ai, predict_optimal_sl_tp
from utils.quantity_utils import calculate_quantity
from utils.sl_tp_utils import calculate_sl_tp
from utils.pnl_tracker import generate_daily_report
from utils.trade_storage import save_trade
from utils.get_klines import get_klines
from backtest_utils import run_backtest
from trade_executor import execute_trade_live
from news_utils import fetch_crypto_news, analyze_news_impact
from utils.scanner_utils import scan_all
from utils.multi_tf_scanner import multi_tf_scan_with_ai
from auto_executor import start_executor_loop, stop_executor_loop, is_executor_running

# טען משתנים מסביבה (אם קיימים)
load_dotenv()

app = FastAPI(
    title="AlgoGPT API",
    description="API למסחר אלגוריתמי בזמן אמת – Binance (Futures, Spot, Grid, GPT, דוחות)",
    version="2.0.1"
)

# MODELS
class SLTPRequest(BaseModel):
    df: list
    direction: str

class QuantityRequest(BaseModel):
    symbol: str
    price: float
    leverage: float
    budget: float

class BacktestRequest(BaseModel):
    prices: list
    symbol: str = "UNKNOWN"
    interval: str = "15m"

class TradeRequest(BaseModel):
    symbol: str
    entry: float
    stop: float
    tp: float
    direction: str
    leverage: int
    budget: float = 100
    use_grid: bool = False
    use_trailing: bool = False
    user_id: str = None
    take_snapshot: bool = True

class AIAnalysisRequest(BaseModel):
    rsi: float
    adx: float
    trend: str
    volume: float
    pattern: str

# ROUTES
@app.get("/")
async def root():
    return {"status": "ok", "message": "AlgoGPT API is running ✅"}

@app.get("/scan")
async def scan_route(
    market: str = "futures",
    interval: str = "1m",
    limit: int = 50,
    min_quality: int = 6,
    min_volume: int = 1_000_000,
    trending_only: bool = False
):
    try:
        results = await scan_all(
            market_type=market,
            interval=interval,
            limit=limit,
            min_quality=min_quality,
            trending_only=trending_only,
            min_volume=min_volume,
            with_ai=True
        )
        return {"count": len(results), "results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/scan/multi")
async def scan_multi(
    min_quality: int = 6,
    top: int = 3,
    frames: str = "1m,5m,15m",
    markets: str = "futures",
    trending_only: bool = False
):
    try:
        timeframes = frames.split(",")
        market_list = markets.split(",")
        results = await multi_tf_scan_with_ai(
            markets=market_list,
            timeframes=timeframes,
            min_quality=min_quality,
            trending_only=trending_only,
            top=top
        )
        return {"count": len(results), "results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/execute-trade")
async def execute_trade(req: TradeRequest):
    try:
        result = execute_trade_live(
            symbol=req.symbol,
            entry=req.entry,
            stop=req.stop,
            tp=req.tp,
            direction=req.direction,
            leverage=req.leverage,
            budget=req.budget,
            use_grid=req.use_grid,
            use_trailing=req.use_trailing,
            user_id=req.user_id,
            take_snapshot=req.take_snapshot
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/calculate-quantity")
async def calc_quantity(q: QuantityRequest):
    try:
        qty = calculate_quantity(q.symbol, q.price, q.leverage, q.budget)
        return {"quantity": qty}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/sl_tp")
async def calc_sl_tp(req: SLTPRequest):
    try:
        result = calculate_sl_tp(req.df, req.direction)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/backtest")
async def run_backtest_route(req: BacktestRequest):
    try:
        df = get_klines(req.symbol, req.interval, limit=200, market_type="futures")
        result = run_backtest(df)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/ai-analyze")
async def ai_analyze(req: AIAnalysisRequest):
    try:
        result = analyze_with_ai(req.rsi, req.adx, req.trend, req.volume, req.pattern)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/news")
async def get_news():
    return fetch_crypto_news()

@app.get("/analyze-news")
async def analyze_news():
    return analyze_news_impact()

@app.get("/daily-report")
async def report_route(date: str = None):
    try:
        return generate_daily_report(date)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/auto/start")
async def start_auto():
    if is_executor_running():
        return {"status": "already running"}
    asyncio.create_task(start_executor_loop())
    return {"status": "started"}

@app.get("/auto/stop")
async def stop_auto():
    stop_executor_loop()
    return {"status": "stopped"}

@app.get("/auto/status")
async def auto_status():
    return {"status": "running" if is_executor_running() else "stopped"}

# אפשור התחלה אוטומטית אם צריך
if os.getenv("AUTO_RUN", "false").lower() == "true":
    asyncio.create_task(start_executor_loop())

# להרצה מקומית
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))

























































































































































































































































































































































































