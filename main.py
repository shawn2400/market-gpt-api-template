# main.py

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
    version=os.getenv("ALGOGPT_VERSION", "2.14.0"),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files (ל־plugin של ChatGPT או Dashboard)
if os.path.isdir(".well-known"):
    app.mount("/.well-known", StaticFiles(directory=".well-known"), name="static")
if os.path.isdir("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

# בריאות
@app.get("/")
def root():
    return {"status": "ok", "version": app.version}

# מדדים
@app.get("/metrics")
async def get_metrics():
    return metrics_tracker.get_metrics()

# ראוטים
app.include_router(trade_router, prefix="/trade", tags=["Trade"])  # אין prefix כפול בתוך הקובץ
app.include_router(ai_router, prefix="/ai", tags=["AI"])           # אין prefix כפול בתוך הקובץ
app.include_router(backtest_router, tags=["Backtest"])             # endpoints כפי שמוגדרים בקובץ

# דשבורד HTML פשוט
from dashboard import router as dashboard_router
app.include_router(dashboard_router, tags=["Dashboard"])

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
























































































































































































































































































