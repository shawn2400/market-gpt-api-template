# main.py
import os
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from routes.trade import router as trade_router
from routes.ai import router as ai_router
from routes.backtest import router as backtest_router
from routes.dashboard import router as dashboard_router
from utils.metrics import metrics_tracker

APP_VERSION = os.getenv("ALGOGPT_VERSION", "2.14.0")

app = FastAPI(
    title="AlgoGPT API",
    description="AlgoGPT — מסחר אלגוריתמי בזמן אמת ל־Binance Futures",
    version=APP_VERSION,
)

# ---- CORS ----
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- Static mounts (ChatGPT plugin + assets/PDFs) ----
if os.path.isdir(".well-known"):
    app.mount("/.well-known", StaticFiles(directory=".well-known"), name="static-plugin")
if os.path.isdir("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

# ---- Health / Root ----
@app.get("/", operation_id="getRootStatus", tags=["Config"])
def root():
    return {"status": "ok", "version": app.version}

@app.get("/metrics", operation_id="getBasicMetrics", tags=["Config"])
async def get_metrics():
    return metrics_tracker.get_metrics()

# ---- Routers ----
# /dashboard HTML (routes/dashboard.py)
app.include_router(dashboard_router, tags=["Dashboard"])

# /ai/*
app.include_router(ai_router, prefix="/ai", tags=["AI"])

# /trade/*
app.include_router(trade_router, prefix="/trade", tags=["Trades"])

# /backtest (הנתיב עצמו מוגדר בתוך הקובץ)
app.include_router(backtest_router, tags=["Backtest"])

# ---- Startup log ----
@app.on_event("startup")
async def on_startup():
    logging.getLogger("uvicorn").info("AlgoGPT API started (v%s)", APP_VERSION)

# ---- Uvicorn entrypoint (local dev) ----
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", 10000)),
        log_level="info",
    )


























































































































































































































































































