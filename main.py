from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from dotenv import load_dotenv
import pandas as pd
import os
import asyncio
import time
import logging

from utils.quantity_utils import calculate_quantity
from utils.sl_tp_utils import calculate_sl_tp
from utils.quality_score import compute_quality_score
from utils.scanner_utils import scan_all
from utils.ai_analysis import analyze_with_ai, predict_optimal_sl_tp
from utils.trade_storage import save_trade_data
from utils.get_live_price import get_live_price
from utils.pnl_tracker import update_pnl
from utils import report_utils
from utils import snapshot_utils
from trade_executor import execute_trade_live
from backtest_utils import run_backtest
from news_utils import get_crypto_news, analyze_news_sentiment
from auto_executor import start_executor_loop, stop_executor_loop, is_executor_running
from utils.multi_tf_scanner import multi_tf_scan_with_ai

# === Bootstrapping ===
__boot_start__ = time.time()
load_dotenv()
logging.basicConfig(level=logging.INFO)
app = FastAPI(
    title="AlgoGPT API",
    description="API למסחר בזמן אמת ב-Binance כולל AI, SL/TP, טריידים, Backtest ודוחות",
    version="2.0.1"
)

# === Models ===
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
    symbol: str
    interval: str

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
    take_snapshot: bool = True
    user_id: str = "system"

# === Routes ===
@app.get("/")
def root():
    return {"status": "ok", "message": "AlgoGPT API is running ✅"}

@app.get("/scan")
async def scan(
    market: str = "futures",
    interval: str = "1m",
    limit: int = 50,
    min_quality: int = 6,
    min_volume: int = 1_000_000,
    trending_only: bool = False
):
    try:
        results = await scan_all(market, interval, limit, min_quality, trending_only, min_volume)
        return {"count": len(results), "results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/scan/multi")
async def scan_multi(
    frames: str = "1m,5m,15m",
    markets: str = "futures",
    min_quality: int = 6,
    top: int = 5,
    trending_only: bool = False
):
    try:
        results = await multi_tf_scan_with_ai(
            timeframes=frames.split(","),
            markets=markets.split(","),
            min_quality=min_quality,
            top=top,
            trending_only=trending_only
        )
        return {"count": len(results), "results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/sl_tp")
def sl_tp(req: SLTPRequest):
    try:
        df = pd.DataFrame(req.df)
        out = calculate_sl_tp(df, req.direction)
        return out
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/calculate-quantity")
def calc_quantity(req: QuantityRequest):
    try:
        q = calculate_quantity(req.symbol, req.price, req.leverage, req.budget)
        return {"quantity": q}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/execute-trade")
def execute_trade(req: TradeRequest):
    try:
        out = execute_trade_live(
            symbol=req.symbol,
            entry=req.entry,
            stop=req.stop,
            tp=req.tp,
            direction=req.direction,
            leverage=req.leverage,
            budget=req.budget,
            use_grid=req.use_grid,
            use_trailing=req.use_trailing,
            take_snapshot=req.take_snapshot,
            user_id=req.user_id
        )
        return out
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/backtest")
def backtest(req: BacktestRequest):
    try:
        df = pd.DataFrame(req.prices)
        out = run_backtest(df, req.symbol, req.interval)
        return out
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/news")
def news():
    return get_crypto_news()

@app.get("/analyze-news")
def analyze_news():
    return analyze_news_sentiment()

@app.get("/daily-report")
def daily_report(date: str = None):
    try:
        result = report_utils.generate_daily_report(date)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/ai-analyze")
def ai_analyze(payload: dict):
    try:
        out = analyze_with_ai(**payload)
        return out
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/executor/status")
def executor_status():
    return {"running": is_executor_running()}

@app.post("/executor/start")
def executor_start():
    start_executor_loop()
    return {"status": "started"}

@app.post("/executor/stop")
def executor_stop():
    stop_executor_loop()
    return {"status": "stopped"}
























































































































































































































































































































































































