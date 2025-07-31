# main.py

import os
import uvicorn
import time
from fastapi import FastAPI
from dotenv import load_dotenv
from routes import ai, trade, multi_scan
from utils.report_utils import generate_daily_report
from utils.quantity_utils import calculate_quantity
from utils.sl_tp_utils import calculate_sl_tp
from utils.ai_analysis import analyze_with_ai
from news_utils import get_latest_news, analyze_news_sentiment
from utils.backtest_utils import run_backtest
from utils.trade_executor import execute_trade_live
from utils.scanner_utils import scan_all
from auto_executor import start_executor_loop, stop_executor_loop, is_executor_running

from pydantic import BaseModel
import pandas as pd

load_dotenv()
app = FastAPI(
    title="AlgoGPT API",
    description="API למסחר חכם עם Binance, AI ודוחות בזמן אמת",
    version="2.0.1"
)

# === DATA MODELS ===

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
    interval: str = "15m"

class TradeRequest(BaseModel):
    symbol: str
    entry: float
    stop: float = None
    target: float = None
    direction: str
    leverage: float = 10
    market: str = "futures"
    budget: float = 100

class ScanRequest(BaseModel):
    market: str = "futures"
    min_quality: int = 6
    top: int = 1
    trending_only: bool = False
    trending_source: str = "coingecko"

# === ROUTES ===

@app.get("/")
def root():
    return {"status": "ok", "message": "AlgoGPT API is running ✅"}

@app.post("/sl_tp")
def sl_tp(req: SLTPRequest):
    return calculate_sl_tp(req.df, req.direction)

@app.post("/calculate-quantity")
def calc_qty(req: QuantityRequest):
    qty = calculate_quantity(req.symbol, req.price, req.leverage, req.budget)
    return {"quantity": qty}

@app.post("/backtest")
def backtest(req: BacktestRequest):
    df = pd.DataFrame(req.prices)
    return run_backtest(df, req.symbol, req.interval)

@app.post("/ai-analyze")
def ai_analyze(payload: dict):
    rsi = payload.get("rsi", 50)
    adx = payload.get("adx", 20)
    trend = payload.get("trend", "up")
    volume = payload.get("volume", "normal")
    pattern = payload.get("pattern", "none")
    return analyze_with_ai(rsi, adx, trend, volume, pattern)

@app.get("/news")
def news():
    return get_latest_news()

@app.get("/analyze-news")
def analyze_news():
    return analyze_news_sentiment()

@app.post("/execute-trade")
def execute_trade(req: TradeRequest):
    return execute_trade_live(req.dict())

@app.post("/scan")
def scan(req: ScanRequest):
    return scan_all(
        market=req.market,
        min_quality=req.min_quality,
        top=req.top,
        trending_only=req.trending_only,
        trending_source=req.trending_source
    )

@app.get("/daily-report")
def daily_report():
    return generate_daily_report()

@app.get("/executor/start")
async def start_executor():
    await start_executor_loop()
    return {"status": "started"}

@app.get("/executor/stop")
def stop_executor():
    stop_executor_loop()
    return {"status": "stopped"}

@app.get("/executor/status")
def executor_status():
    return {"running": is_executor_running()}

# הוספת נתיבים חיצוניים (מתוך routes/)
app.include_router(ai.router)
app.include_router(trade.router)
app.include_router(multi_scan.router)

# === ENTRY POINT ===
if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=5000, reload=True)






























































































































































































































































































































































































