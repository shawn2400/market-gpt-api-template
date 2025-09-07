# main.py
from __future__ import annotations
import os, logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# ──────────────────────────────────────────────
# Routers
# ──────────────────────────────────────────────
from routes import (
    ai,
    trade,
    backtest,
    executor,
    export,
    orders,
    grid,
    dashboard_live,
    risk_tools,
    telegram_bot,   # ✅ נשאר
    # telegram_callbacks ❌ הוסר – התמזג לתוך telegram_bot
)

# ──────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger("algogpt.main")

# ──────────────────────────────────────────────
# FastAPI App
# ──────────────────────────────────────────────
app = FastAPI(
    title="AlgoGPT API",
    version=os.getenv("ALGOGPT_VERSION", "2.17.0"),
    description="🚀 AlgoGPT – Algorithmic Trading API with AI + Binance Futures",
)

# ──────────────────────────────────────────────
# CORS
# ──────────────────────────────────────────────
origins = os.getenv("CORS_ALLOW_ORIGINS", "*")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origins] if origins != "*" else ["*"],
    allow_credentials=os.getenv("CORS_ALLOW_CREDENTIALS", "0") == "1",
    allow_methods=["*"],
    allow_headers=["*"],
)

# ──────────────────────────────────────────────
# Routers Include
# ──────────────────────────────────────────────
app.include_router(ai.router)
app.include_router(trade.router)
app.include_router(backtest.router)
app.include_router(executor.router)
app.include_router(export.router)
app.include_router(orders.router)
app.include_router(grid.router)
app.include_router(dashboard_live.router)
app.include_router(risk_tools.router)
app.include_router(telegram_bot.router)  # ✅ מאוחד (כולל גם callbacks)

# ──────────────────────────────────────────────
# Root Endpoint
# ──────────────────────────────────────────────
@app.get("/")
async def root():
    return {
        "ok": True,
        "name": "AlgoGPT API",
        "version": os.getenv("ALGOGPT_VERSION", "2.17.0"),
        "env": os.getenv("ENV", "production"),
    }

# ──────────────────────────────────────────────
# Healthcheck
# ──────────────────────────────────────────────
@app.get("/healthz")
async def healthz():
    return {"ok": True, "status": "healthy"}




































































































































































































































































































































































































































































































































