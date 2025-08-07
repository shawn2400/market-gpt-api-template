import os
import json
import logging
import threading
import asyncio
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

# === טעינת ENV ===
load_dotenv()

# === ייבוא ראוטים ולוגיקה ===
from routes.ai import router as ai_router
from routes.trade import router as trade_router
from routes.grid import router as grid_router
from routes.multi_scan import router as multi_router
from auto_executor import start_executor_loop, stop_executor_loop, is_executor_running
from utils.ws_fallback import launch_multi_websocket, get_price

# === לוגים ===
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(message)s',
    force=True
)

# === בדיקת ENV קריטיים ===
REQUIRED_ENV_VARS = [
    "BINANCE_API_KEY", "BINANCE_API_SECRET", "OPENAI_API_KEY",
    "AUTO_RUN", "MIN_QUALITY_SCORE", "MAX_TRADE_BUDGET", "SCAN_INTERVAL"
]
for var in REQUIRED_ENV_VARS:
    if not os.getenv(var):
        logging.error(f"❌ Missing required environment variable: {var}")
        raise RuntimeError(f"❌ Missing required environment variable: {var}")

# === משתנים מערכתיים ===
AUTO_RUN = os.getenv("AUTO_RUN", "false").lower() == "true"
MIN_QUALITY_SCORE = int(os.getenv("MIN_QUALITY_SCORE", 6))
MAX_TRADE_BUDGET = float(os.getenv("MAX_TRADE_BUDGET", 100))
SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL", 60))

# === קריאת רשימת מעקב ===
def load_watchlist_symbols():
    try:
        with open("watchlist.json", "r") as f:
            data = json.load(f)
            return [entry["symbol"].upper() for entry in data if isinstance(entry, dict) and "symbol" in entry]
    except Exception as e:
        logging.warning(f"[main] ⚠️ שגיאה בקריאת watchlist.json: {e}")
        return ["BTCUSDT"]

# === WebSocket חכם ===
WS_LAUNCHED = False

def start_ws_multi_background():
    global WS_LAUNCHED
    if WS_LAUNCHED:
        logging.info("[main] WS Multi כבר רץ, מדלג.")
        return

    symbols = load_watchlist_symbols()

    def run_ws():
        asyncio.run(launch_multi_websocket(symbols))

    t = threading.Thread(target=run_ws, daemon=True)
    t.start()
    logging.info(f"[main] 🚀 WebSocket הופעל עבור: {symbols}")
    WS_LAUNCHED = True

# === יצירת FastAPI ===
app = FastAPI(
    title="AlgoGPT API",
    description="API למסחר בזמן אמת ב‎Binance (Futures, Spot, Grid, AI, SL/TP)",
    version="2.0.6"
)

# === קבצים סטטיים ===
if os.path.isdir(".well-known"):
    app.mount("/.well-known", StaticFiles(directory=".well-known"), name="well-known")
else:
    logging.info("ℹ️ התיקייה '.well-known' לא קיימת – לא בוצע mount.")

if os.path.isdir("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")
else:
    logging.info("ℹ️ התיקייה 'static' לא קיימת – לא בוצע mount.")

# === CORS ===
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# === ראוטים ===
app.include_router(ai_router)
app.include_router(trade_router)
app.include_router(grid_router)
app.include_router(multi_router)

# === אתחול רקע ===
@app.on_event("startup")
async def startup_event():
    start_ws_multi_background()
    if AUTO_RUN:
        if start_executor_loop():
            logging.info("✅ AutoExecutor הופעל אוטומטית.")
        else:
            logging.info("ℹ️ AutoExecutor כבר פעיל.")

# === ברירת מחדל ===
@app.get("/")
async def root():
    return {"status": "ok", "message": "AlgoGPT API is running ✅"}

# === שליטה ב־AutoExecutor ===
@app.get("/executor/start")
async def start_executor():
    started = start_executor_loop()
    return {"status": "started" if started else "already running"}

@app.get("/executor/stop")
async def stop_executor():
    stopped = stop_executor_loop()
    return {"status": "stopped" if stopped else "not running"}

@app.get("/executor/status")
async def executor_status():
    return {"running": is_executor_running()}

# === שליפת מחיר ===
@app.get("/price")
async def get_price_route(symbol: str = Query(..., description="Symbol כמו BTCUSDT")):
    try:
        price = await get_price(symbol)
        if price is None:
            return {"error": "לא נמצא מחיר"}
        return {"symbol": symbol, "price": price}
    except Exception as e:
        logging.error(f"[main] שגיאה בשליפת מחיר: {e}")
        return {"error": str(e)}

# === בדיקת ראוטים קיימים ===
@app.get("/debug/routes")
def get_routes():
    return [{"path": route.path, "name": route.name} for route in app.router.routes]
























































































































































































































































































































































































































































































































































































































































































































































































































































