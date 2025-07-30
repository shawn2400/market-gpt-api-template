import os
import sys
import time
import threading
import asyncio
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from dotenv import load_dotenv
import pandas as pd

sys.path.append(os.path.dirname(__file__))
__boot_start__ = time.time()
load_dotenv()

from utils.ai_analysis import analyze_with_ai
from auto_executor import start_executor_loop, stop_executor_loop, is_executor_running
from utils.watchlist_utils import load_watchlist, add_to_watchlist
from utils.multi_tf_scanner import multi_tf_scan_with_ai

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
    grid_mode: str = "FUTURES"

class AIAnalysisRequest(BaseModel):
    rsi: float
    adx: float
    trend: str
    volume: float
    pattern: str

app = FastAPI(
    title="AlgoGPT API PRO Ultra",
    version="2.0.1",
    description="API למסחר אלגוריתמי (Binance, Trending, Multi-TF, AI, Watchlist, דוחות, REST)"
)

@app.get("/")
async def home():
    return {"status": "ok", "message": "AlgoGPT API is running ✅"}

@app.post("/sl_tp")
async def sl_tp(request: SLTPRequest):
    try:
        from utils.sl_tp_utils import calculate_sl_tp_adaptive
        df = pd.DataFrame(request.df)
        return calculate_sl_tp_adaptive(df, request.direction)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/calculate-quantity")
async def calc_qty(data: QuantityRequest):
    try:
        from utils.calculate_quantity import calculate_quantity
        q = calculate_quantity(data.symbol, data.price, data.leverage, data.budget)
        return {"quantity": q}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/news")
async def news():
    try:
        from news_utils import fetch_crypto_news
        return fetch_crypto_news()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/analyze-news")
async def analyze_news():
    try:
        from news_utils import fetch_crypto_news, analyze_news_impact
        news = fetch_crypto_news()
        return analyze_news_impact(news)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/backtest")
async def backtest(request: BacktestRequest):
    try:
        from backtest_utils import run_backtest
        if not request.prices or len(request.prices) < 30:
            raise HTTPException(status_code=400, detail="Insufficient data – at least 30 candles required")
        df = pd.DataFrame(request.prices)
        for col in ['open','high','low','close','volume']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        df.dropna(inplace=True)
        if df.empty:
            raise HTTPException(status_code=400, detail="No valid rows after cleaning")
        results = run_backtest(df)
        return {
            "symbol": request.symbol,
            "interval": request.interval,
            "results": results.to_dict(orient="records"),
            "success_count": int(results.get("success", []).count(True)),
            "total_trades": len(results),
            "avg_quality": round(results.get("quality_score", []).mean(), 2) if not results.empty else 0
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/execute-trade")
async def execute_trade(data: TradeRequest):
    try:
        if data.use_grid:
            from utils.grid_utils import execute_grid
            is_fut = data.grid_mode.upper() == "FUTURES"
            return await asyncio.to_thread(
                execute_grid,
                symbol=data.symbol,
                budget=data.budget,
                grid_count=8,
                grid_pct=0.5,
                leverage=data.leverage,
                futures=is_fut,
                direction="BOTH",
                tp_pct=1,
                sl_pct=1
            )
        else:
            from trade_executor import execute_trade_live
            return await asyncio.to_thread(
                execute_trade_live,
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

@app.get("/scan")
async def scan_market(
    min_quality: int = Query(0),
    interval: str = Query("1m"),
    limit: int = Query(300),
    trending_only: bool = Query(False),
    min_volume: int = Query(1_000_000)
):
    try:
        from utils.scanner_utils import scan_all
        results = await scan_all(
            interval=interval,
            limit=limit,
            min_quality=min_quality,
            trending_only=trending_only,
            min_volume=min_volume
        )
        return {"count": len(results), "results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/scan/multi")
async def scan_multi(
    min_quality: int = Query(6),
    top: int = Query(10),
    trending_only: bool = Query(False),
    frames: str = Query("1m,3m,5m,15m,1h"),
    markets: str = Query("futures,spot"),
    trending_source: str = Query("coingecko")
):
    try:
        tf_list = tuple(f.strip() for f in frames.split(","))
        mk_list = tuple(m.strip() for m in markets.split(","))
        results = await multi_tf_scan_with_ai(
            timeframes=tf_list,
            markets=mk_list,
            min_quality=min_quality,
            top=top,
            trending_only=trending_only,
            trending_source=trending_source
        )
        return {"count": len(results), "results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/watchlist")
async def get_watchlist():
    try:
        wl = load_watchlist()
        return {"count": len(wl), "watchlist": wl}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/watchlist/add")
async def add_watchlist_api(symbol: str, direction: str, quality_score: int=7, reason: str="הוסף ידנית"):
    try:
        ok = add_to_watchlist(symbol, direction, quality_score, reason)
        return {"status": "ok" if ok else "exists"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/daily-report")
async def daily_report():
    try:
        from report_utils import generate_daily_report
        return generate_daily_report()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/ai-analyze")
async def ai_analyze(data: AIAnalysisRequest):
    try:
        return analyze_with_ai(data.dict())
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/start-auto")
async def start_auto():
    global _executor_thread
    if is_executor_running():
        return {"status": "already running"}
    delay = int(os.getenv("SCAN_INTERVAL", "60"))
    min_q = int(os.getenv("MIN_QUALITY_SCORE", "6"))
    budget = float(os.getenv("MAX_TRADE_BUDGET", "100"))
    _executor_thread = threading.Thread(
        target=lambda: start_executor_loop(debug=False, delay=delay, min_quality=min_q, max_budget=budget),
        daemon=True
    )
    _executor_thread.start()
    return {"status": "started"}

@app.post("/stop-auto")
async def stop_auto():
    stop_executor_loop()
    return {"status": "stopped"}

@app.get("/status")
async def executor_status():
    running = is_executor_running()
    return {"executor_running": running, "message": "✅ פעל" if running else "🚩 לא פעיל"}

@app.on_event("startup")
async def on_startup():
    print(f"[BOOT TIME] ready in {time.time() - __boot_start__:.2f}s")
    if os.getenv("AUTO_RUN", "true").lower() == "true":
        delay = int(os.getenv("SCAN_INTERVAL", "60"))
        min_q = int(os.getenv("MIN_QUALITY_SCORE", "6"))
        budget = float(os.getenv("MAX_TRADE_BUDGET", "100"))
        threading.Thread(
            target=lambda: start_executor_loop(debug=False, delay=delay, min_quality=min_q, max_budget=budget),
            daemon=True
        ).start()

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "5000"))
    uvicorn.run("main:app", host="0.0.0.0", port=port)


















































































































































































































































































































































































