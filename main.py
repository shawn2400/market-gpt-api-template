import os
import json
import logging
import asyncio
from typing import Optional

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

from utils.ws_fallback import launch_multi_websocket, get_price
from auto_executor import start_executor, stop_executor, is_executor_running

load_dotenv()
logging.basicConfig(level=logging.INFO,
                    format='[%(asctime)s] [%(levelname)s] %(message)s',
                    force=True)

BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MAX_WS_SYMBOLS = int(os.getenv("MAX_WS_SYMBOLS", 15))

logging.info(f"[ENV] Binance API Key Loaded: {'Yes' if BINANCE_API_KEY else 'No'}")
logging.info(f"[ENV] Binance API Secret Loaded: {'Yes' if BINANCE_API_SECRET else 'No'}")
logging.info(f"[ENV] OpenAI API Key Loaded: {'Yes' if OPENAI_API_KEY else 'No'}")
logging.info(f"[ENV] Max WS Symbols: {MAX_WS_SYMBOLS}")

def load_watchlist_symbols() -> list[str]:
    try:
        with open("watchlist.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        symbols = [str(x.get("symbol", "")).upper()
                   for x in data
                   if isinstance(x, dict) and x.get("symbol")]
        if not symbols:
            raise ValueError("רשימת המעקב ריקה")
        logging.info(f"[watchlist] Loaded {len(symbols)} symbols, trimming to {MAX_WS_SYMBOLS}")
        return symbols[:MAX_WS_SYMBOLS]
    except Exception as e:
        logging.warning(f"[main] ⚠️ שגיאה בקריאת watchlist.json: {e} – נטען BTCUSDT בלבד")
        return ["BTCUSDT"]

app = FastAPI(
    title="AlgoGPT API",
    description="API למסחר בזמן אמת ב-Binance (Futures, Spot, Grid, AI, SL/TP)",
    version="2.0.9",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

if os.path.isdir(".well-known"):
    app.mount("/.well-known", StaticFiles(directory=".well-known"), name="well-known")
if os.path.isdir("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

try:
    from routes.ai import router as ai_router
    from routes.trade import router as trade_router
    from routes.grid import router as grid_router
    from routes.multi_scan import router as multi_router

    app.include_router(ai_router)
    app.include_router(trade_router)
    app.include_router(grid_router)
    app.include_router(multi_router)
    logging.info("[main] Routers included successfully")
except Exception as e:
    logging.exception(f"[main] Failed to include routers: {e}")

_ws_task: Optional[asyncio.Task] = None

@app.on_event("startup")
async def startup_event():
    logging.info("[main] Server startup event triggered")
    symbols = load_watchlist_symbols()
    global _ws_task
    _ws_task = asyncio.create_task(launch_multi_websocket(symbols))
    logging.info(f"[main] WS task spawned for {len(symbols)} symbols")

@app.on_event("shutdown")
async def shutdown_event():
    global _ws_task
    if _ws_task and not _ws_task.done():
        _ws_task.cancel()
        try:
            await asyncio.wait_for(_ws_task, timeout=5)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logging.warning(f"[main] WS task cancel error: {e}")

@app.get("/")
async def root():
    return {"status": "ok", "message": "AlgoGPT API is running ✅", "docs": "/docs"}

@app.get("/healthz")
async def healthz():
    return {"status": "healthy ✅"}

@app.get("/executor/start")
async def start_executor_route():
    started = start_executor()
    return {"status": "started" if started else "already running"}

@app.get("/executor/stop")
async def stop_executor_route():
    stopped = stop_executor()
    return {"status": "stopped" if stopped else "not running"}

@app.get("/executor/status")
async def executor_status_route():
    return {"running": is_executor_running()}

@app.get("/price")
async def get_price_route(symbol: str = Query(..., description="סימבול כמו BTCUSDT")):
    try:
        price = await get_price(symbol)
        if price is None:
            return {"error": "לא נמצא מחיר"}
        return {"symbol": symbol.upper(), "price": price}
    except Exception as e:
        logging.error(f"[main] שגיאה בשליפת מחיר: {e}")
        return {"error": str(e)}

@app.get("/debug/routes")
def get_routes():
    info = [{"path": r.path, "name": r.name} for r in app.router.routes]
    logging.info(f"[debug] Registered routes: {info}")
    return info



















