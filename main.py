# main.py

import os
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv

# === Imports פנימיים ===
from utils.quantity_utils import calculate_quantity
from utils.sl_tp_utils import calculate_sl_tp
from utils.ai_analysis import analyze_with_ai
from utils.backtest_utils import run_backtest
from utils.report_utils import generate_daily_report
from utils.trade_executor import execute_trade_live
from utils.scanner_utils import scan_all, analyze_symbol
from utils.multi_tf_scanner import multi_tf_scan_with_ai
from news_utils import get_latest_news, analyze_news_sentiment
from auto_executor import start_executor_loop, stop_executor_loop, is_executor_running

load_dotenv()

app = FastAPI(
    title="AlgoGPT API",
    description="API למסחר חכם עם Binance, AI ודוחות בזמן אמת",
    version="2.0.1"
)

# === MODELS ===

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

class MultiTFScanRequest(BaseModel):
    markets: list = ["futures"]
    timeframes: list = ["5m", "15m", "1h"]
    trending_only: bool = False
    top: int = 3
    trending_source: str = "coingecko"

class AnalyzeSymbolRequest(BaseModel):
    symbol: str
    interval: str = "15m"
    market: str = "futures"
    with_ai: bool = True
    min_quality: int = 6
    min_volume: float = 0

# === ROUTES ===

@app.get("/")
def root():
    return {"status": "ok", "message": "AlgoGPT API is live ✅"}

@app.post("/sl_tp", tags=["SL/TP"])
def sl_tp(req: SLTPRequest):
    try:
        return calculate_sl_tp(req.df, req.direction)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/calculate-quantity", tags=["Quantity"])
def calc_qty(req: QuantityRequest):
    try:
        qty = calculate_quantity(req.symbol, req.price, req.leverage, req.budget)
        return {"quantity": qty}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/backtest", tags=["Backtest"])
def backtest(req: BacktestRequest):
    try:
        import pandas as pd
        df = pd.DataFrame(req.prices)
        return run_backtest(df, req.symbol, req.interval)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/ai-analyze", tags=["AI"])
def ai_analyze(payload: dict):
    try:
        rsi = payload.get("rsi", 50)
        adx = payload.get("adx", 20)
        trend = payload.get("trend", "up")
        volume = payload.get("volume", "normal")
        pattern = payload.get("pattern", "none")
        return analyze_with_ai(rsi, adx, trend, volume, pattern)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/news", tags=["News"])
def news():
    try:
        return get_latest_news()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/analyze-news", tags=["News"])
def analyze_news():
    try:
        return analyze_news_sentiment()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/execute-trade", tags=["Trade"])
def execute_trade(req: TradeRequest):
    try:
        return execute_trade_live(req.dict())
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/scan", tags=["Scan"])
def scan(req: ScanRequest):
    try:
        return scan_all(
            market=req.market,
            min_quality=req.min_quality,
            top=req.top,
            trending_only=req.trending_only,
            trending_source=req.trending_source
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/scan/multi", tags=["Scan"])
async def scan_multi(req: MultiTFScanRequest):
    try:
        return await multi_tf_scan_with_ai(
            markets=req.markets,
            timeframes=req.timeframes,
            trending_only=req.trending_only,
            top=req.top,
            trending_source=req.trending_source
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/analyze-symbol", tags=["Scan"])
def analyze_symbol_post(req: AnalyzeSymbolRequest):
    try:
        result = analyze_symbol(
            symbol=req.symbol,
            interval=req.interval,
            market_type=req.market,
            with_ai=req.with_ai,
            min_quality=req.min_quality,
            min_volume=req.min_volume,
            frames=[req.interval]
        )
        if not result:
            raise HTTPException(status_code=404, detail="לא נמצא טרייד מתאים")
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/daily-report", tags=["Reports"])
def daily_report():
    try:
        return generate_daily_report()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/executor/start", tags=["Executor"])
async def start_executor():
    try:
        await start_executor_loop()
        return {"status": "started"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/executor/stop", tags=["Executor"])
def stop_executor():
    try:
        stop_executor_loop()
        return {"status": "stopped"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/executor/status", tags=["Executor"])
def executor_status():
    return {"running": is_executor_running()}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=5000)






























































































































































































































































































































































































