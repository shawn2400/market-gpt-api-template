from __future__ import annotations
import os, asyncio, logging, json, time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles

load_dotenv(override=True)

from utils.config import (
    check_config, dump_config_sanitized, LOG_LEVEL,
    WS_UPDATE_INTERVAL, PRICE_MONITOR_INTERVAL,
    PRICE_WS_FRESH_TTL, PRICE_MONITOR_DISABLE,
    ENABLE_AI_ROUTES, OPENAI_API_KEY
)

from utils.json_logger import setup_json_logging
from utils.ws_fallback import auto_price_updater, LAST_PRICE_CACHE, update_price
from utils.watchlist_utils import load_watchlist
from utils.binance_client import futures_mark_price
from utils.anchor import evaluate_anchor
from utils.rate_limit import RateLimitMiddleware
from utils import cache_fallback as redis_store
from utils.auth import require_api_key

APP_VERSION=os.getenv("ALGOGPT_VERSION","2.14.6")
logger=setup_json_logging()
logging.getLogger().setLevel(LOG_LEVEL)

# FastAPI app
app=FastAPI(title="AlgoGPT API",version=APP_VERSION)

# Middlewares
app.add_middleware(ResponseSizeLimiter,max_bytes=int(os.getenv("RESPONSE_MAX_BYTES",1_048_576)))
app.add_middleware(GZipMiddleware,minimum_size=1000)
app.add_middleware(CORSMiddleware,allow_origins=["*"],allow_methods=["*"],allow_headers=["*"])

# Routers
from routes.ai import router as ai_router
from routes.multi_scan import router as scan_router
from routes.trade import router as trade_router
from routes.grid import router as grid_router
from routes.orderflow import router as orderflow_router
from routes.indicators import router as indicators_router
from routes.anchor import router as anchor_router
from routes.debug import router as debug_router

protected_routers=[
    (scan_router,"",["Scan"]),
    (trade_router,"/trade",["Trade"]),
    (grid_router,"/grid",["Grid"]),
    (orderflow_router,"/orderflow",["Orderflow"]),
    (indicators_router,"/indicators",["Indicators"]),
    (anchor_router,"",["Anchor"]),
]

# ✅ AI רק אם מופעל
if ENABLE_AI_ROUTES and OPENAI_API_KEY:
    protected_routers.append((ai_router,"/ai",["AI"]))

for r,p,t in protected_routers:
    app.include_router(r,prefix=p,tags=t,dependencies=[Depends(require_api_key)])

app.include_router(debug_router,prefix="/debug",tags=["Debug"])






























































































































































































































































































































































































































