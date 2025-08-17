from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os

from routes.trade import router as trade_router
from routes.ai import router as ai_router
from routes.backtest import router as backtest_router
from utils.metrics import metrics_tracker

app = FastAPI(
    title="AlgoGPT API",
    description="AlgoGPT — מסחר אלגוריתמי בזמן אמת ל־Binance Futures",
    version=os.getenv("ALGOGPT_VERSION", "2.14.0")
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

if os.path.isdir(".well-known"):
    app.mount("/.well-known", StaticFiles(directory=".well-known"), name="static")

@app.get("/")
def root():
    return {"status": "ok", "version": app.version}

@app.get("/metrics")
async def get_metrics():
    return metrics_tracker.get_metrics()

app.include_router(trade_router, prefix="/trade", tags=["Trade"])
app.include_router(ai_router, prefix="/ai", tags=["AI"])
app.include_router(backtest_router, tags=["Backtest"])

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 10000)))























































































































































































































































































