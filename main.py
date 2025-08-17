from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os

# Routers
from routes.trade import router as trade_router
from routes.ai import router as ai_router

# Metrics
from utils.metrics import metrics_tracker

app = FastAPI(
    title="AlgoGPT API",
    description="Automated trading assistant for Binance Futures",
    version=os.getenv("ALGOGPT_VERSION", "1.0.0"),
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files (ל־plugin של ChatGPT)
if os.path.isdir(".well-known"):
    app.mount("/.well-known", StaticFiles(directory=".well-known"), name="static")

# Health check
@app.get("/")
def root():
    return {"status": "ok", "version": app.version}

# 🔍 Metrics endpoint
@app.get("/metrics")
async def get_metrics():
    return metrics_tracker.get_metrics()

# Include routes
app.include_router(trade_router, prefix="/trade")
app.include_router(ai_router, prefix="/ai")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 10000)))





















































































































































































































































































