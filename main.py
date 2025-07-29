### ✅ main.py – קובץ API ראשי
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv
import pandas as pd
import os
import asyncio

from backtest_utils import run_backtest
from news_utils import fetch_crypto_news, analyze_news_impact
from utils.quantity_utils import calculate_quantity
from utils.sl_tp_utils import calculate_sl_tp
from utils.trade_storage import save_trade
from snapshot_utils import save_trade_snapshot
from trade_executor import execute_trade_live
from scanner_utils import scan_all_futures
from report_utils import generate_daily_report
from ai_analysis import analyze_with_ai
from auto_executor import start_auto_executor

load_dotenv()

app = FastAPI(title="AlgoGPT API", description="API למסחר אלגוריתמי עם Binance", version="1.3.0")

# === Data Models ===
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

class AIAnalysisRequest(BaseModel):
    prices: list

# === Routes ===
@app.get("/")
async def home():
    return {"status": "ok", "message": "AlgoGPT API is running ✅"}

@app.post("/sl_tp")
async def sl_tp(request: SLTPRequest):
    try:
        df = pd.DataFrame(request.df)
        result = calculate_sl_tp(df, request.direction)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/calculate-quantity")
async def calc_qty(data: QuantityRequest):
    try:
        quantity = calculate_quantity(data.symbol, data.price, data.leverage, data.budget)
        return {"quantity": quantity}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/news")
async def news():
    return fetch_crypto_news()

@app.get("/analyze-news")
async def analyze_news():
    news = fetch_crypto_news()
    return analyze_news_impact(news)

@app.post("/backtest")
async def backtest(request: BacktestRequest):
    try:
        if not request.prices or len(request.prices) < 30:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "Insufficient data – at least 30 candles are required",
                    "symbol": request.symbol,
                    "interval": request.interval,
                    "code": "ERR_TOO_SHORT"
                }
            )

        df = pd.DataFrame(request.prices)
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = pd.to_numeric(df[col], errors='coerce')

        df.dropna(inplace=True)
        if df.empty:
            raise HTTPException(status_code=400, detail="No valid rows after cleaning")

        results = run_backtest(df)
        return {
            "symbol": request.symbol,
            "interval": request.interval,
            "results": results.to_dict(orient="records"),
            "success_count": int(results["success"].sum()),
            "total_trades": len(results),
            "avg_quality": round(results["quality_score"].mean(), 2) if not results.empty else 0
        }

    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/execute-trade")
async def execute_trade(data: TradeRequest):
    try:
        result = await execute_trade_live(
            symbol=data.symbol,
            entry=data.entry,
            stop=data.stop,
            tp=data.tp,
            direction=data.direction,
            leverage=data.leverage,
            budget_usd=data.budget,
            use_grid=data.use_grid,
            use_trailing=data.use_trailing,
            user_id=data.user_id
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/scan")
async def scan():
    try:
        results = await scan_all_futures()
        return {"results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/daily-report")
async def daily_report():
    try:
        result = generate_daily_report()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/ai-analyze")
async def ai_analyze(data: AIAnalysisRequest):
    try:
        return analyze_with_ai(data.prices)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.on_event("startup")
async def start_background_tasks():
    auto_run = os.getenv("AUTO_RUN", "true").lower()
    min_quality = int(os.getenv("MIN_QUALITY_SCORE", 6))
    max_trade_budget = float(os.getenv("MAX_TRADE_BUDGET", 100))

    if auto_run == "true":
        asyncio.create_task(start_auto_executor(delay=30, min_quality=min_quality, max_budget=max_trade_budget))
































































































































































