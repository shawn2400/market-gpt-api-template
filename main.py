from __future__ import annotations

import os
import asyncio
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

# Load .env from environment (Railway/Render or local override)
load_dotenv()
PORT = int(os.getenv("PORT", 8000))
AUTO_RUN = os.getenv("AUTO_RUN", "false").lower() == "true"

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("AlgoGPT")

# FastAPI App
app = FastAPI(
    title="AlgoGPT",
    version=os.getenv("ALGOGPT_VERSION", "2.13.4")
)

# CORS (Allow all origins)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Include routers
from routes.ai import router as ai_router
from routes.trade import router as trade_router
from routes.grid import router as grid_router
from routes.multi_scan import router as scan_router

app.include_router(ai_router, prefix="/ai", tags=["AI Analysis"])
app.include_router(trade_router, prefix="/trade", tags=["Trading"])
app.include_router(grid_router, prefix="/grid", tags=["Smart Grid"])
app.include_router(scan_router, prefix="/scan", tags=["Scanner"])

# Load watchlist and launch WebSocket prices
from utils.ws_fallback import launch_websocket
from utils.watchlist_utils import load_watchlist

watchlist = load_watchlist()
symbols = [item["symbol"] for item in watchlist]

# Launch WebSocket for price feed
asyncio.create_task(launch_websocket(symbols))

# Launch Auto Executor if enabled
if AUTO_RUN:
    from auto_executor import run_auto_executor
    asyncio.create_task(run_auto_executor())

# Health check endpoint
@app.get("/")
async def health():
    return {"status": "ok", "version": app.version}

















































































































































































































































































