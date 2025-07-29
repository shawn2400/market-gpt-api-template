from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from dotenv import load_dotenv
import pandas as pd
import os
import asyncio
import time
from utils.ai_analysis import analyze_with_ai

__boot_start__ = time.time()
load_dotenv()

app = FastAPI(
    title="AlgoGPT API",
    description="API למסחר אלגוריתמי עם Binance",
    version="1.3.1"
)

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
    take_snapshot: bool = True

class AIAnalysisRequest(BaseModel):
    rsi: float
    adx: float
    trend: str
    volume: float
    pattern: str


# === Routes ===

@app.get("/", operation_id="checkServerStatus")
async def home():
    return {"status": "ok", "message": "AlgoGPT API is running ✅"}


@app.post("/sl_tp", operation_id="calculateSLTP")
async def sl_tp(request: SLTPRequest):
    try:
        from utils.sl_tp_utils import calculate_sl_tp_adaptive
        df = pd.DataFrame(request.df)
        return calculate_sl_tp_adaptive(df, request.direction)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/calculate-quantity", operation_id="calculateQuantity")
async def calc_qty(data: QuantityRequest):
    try:
        from utils.quantity_utils import calculate_quantity
        quantity = calculate_quantity(data.symbol, data.price, data.leverage, data.budget)
        return {"quantity": quantity}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/news", operation_id="fetchCryptoNews")
async def news():
    try:
        from news_utils import fetch_crypto_news
        return fetch_crypto_news()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/analyze-news", operation_id="analyzeNewsImpact")
async def analyze_news():
    try:
        from news_utils import fetch_crypto_news, analyze_news_impact
        news = fetch_crypto_news()
        return analyze_news_impact(news)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/backtest", operation_id="runBacktest")
async def backtest(request: BacktestRequest):
    try:
        from backtest_utils import run_backtest

        if not request.prices or len(request.prices) < 30:
            raise HTTPException(status_code=400, detail={
                "error": "Insufficient data – at least 30 candles are required",
                "symbol": request.symbol,
                "interval": request.interval,
                "code": "ERR_TOO_SHORT"
            })

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


@app.post("/execute-trade", operation_id="executeTrade")
async def execute_trade(data: TradeRequest):
    try:
        from trade_executor import execute_trade_live
        return await execute_trade_live(
            symbol=data.symbol,
            entry=data.entry,
            stop=data.stop,
            tp=data.tp,
            direction=data.direction,
            leverage=data.leverage,
            budget_usd=data.budget,
            use_grid=data.use_grid,
            use_trailing=data.use_trailing,
            user_id=data.user_id,
            take_snapshot=data.take_snapshot
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/scan", operation_id="scanMarket")
async def scan(
    min_quality: int = Query(0, description="ציון איכות מינימלי"),
    interval: str = Query("1m", description="טיימפריים לניתוח"),
    limit: int = Query(300, description="מספר מטבעות לבדיקה")
):
    try:
        from scanner_utils import scan_all_futures
        results = await scan_all_futures(interval=interval, symbol_limit=limit)
        filtered = [r for r in results if r.get("quality_score", 0) >= min_quality]
        return {"count": len(filtered), "results": filtered}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/daily-report", operation_id="generateDailyReport")
async def daily_report():
    try:
        from report_utils import generate_daily_report
        return generate_daily_report()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/ai-analyze", operation_id="aiAnalysis")
async def ai_analyze(data: AIAnalysisRequest):
    try:
        return analyze_with_ai(data.dict())
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.on_event("startup")
async def start_background_tasks():
    try:
        from auto_executor import start_auto_executor

        auto_run = os.getenv("AUTO_RUN", "true").lower()
        min_quality = int(os.getenv("MIN_QUALITY_SCORE", 6))
        max_trade_budget = float(os.getenv("MAX_TRADE_BUDGET", 100))
        delay = int(os.getenv("SCAN_INTERVAL", 30))

        if auto_run == "true":
            print(f"[AUTO_EXECUTOR] Running with MIN_QUALITY_SCORE={min_quality} MAX_TRADE_BUDGET={max_trade_budget}")
            asyncio.create_task(start_auto_executor(
                delay=delay,
                min_quality=min_quality,
                max_budget=max_trade_budget
            ))

        print(f"[BOOT TIME] Server ready in {time.time() - __boot_start__:.2f} seconds")

    except Exception as e:
        print(f"[ERROR on startup] Auto Executor failed to launch: {e}")












































































































































































