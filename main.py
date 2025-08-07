import os
import json
import logging
import threading
import asyncio
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
from utils.ws_fallback import launch_multi_websocket, get_price

# === טעינת ENV ===
load_dotenv()

# === הגדרת לוגים עם פורמט מפורט ===
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(message)s',
    force=True
)

# === בדיקת מפתחות קריטיים בסביבה ===
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MAX_WS_SYMBOLS = int(os.getenv("MAX_WS_SYMBOLS", 15))  # ברירת מחדל 15

logging.info(f"[ENV] Binance API Key Loaded: {'Yes' if BINANCE_API_KEY else 'No'}")
logging.info(f"[ENV] Binance API Secret Loaded: {'Yes' if BINANCE_API_SECRET else 'No'}")
logging.info(f"[ENV] OpenAI API Key Loaded: {'Yes' if OPENAI_API_KEY else 'No'}")
logging.info(f"[ENV] Max WS Symbols: {MAX_WS_SYMBOLS}")

# === קריאת רשימת מעקב עם הגבלה ===
def load_watchlist_symbols():
    try:
        with open("watchlist.json", "r") as f:
            data = json.load(f)
            symbols = [entry["symbol"].upper() for entry in data if isinstance(entry, dict) and "symbol" in entry]
            if not symbols:
                raise ValueError("רשימה ריקה")
            logging.info(f"[watchlist] Loaded {len(symbols)} symbols, trimming to {MAX_WS_SYMBOLS}")
            return symbols[:MAX_WS_SYMBOLS]
    except Exception as e:
        logging.warning(f"[main] ⚠️ שגיאה בקריאת watchlist.json: {e} – נטען BTCUSDT בלבד")
        return ["BTCUSDT"]

# === WebSocket חכם עם הגבלה ===
WS_LOCK_PATH = "/tmp/ws_running.lock"

def start_ws_multi_background():
    if os.path.exists(WS_LOCK_PATH):
        logging.info("[main] 🔒 WebSocket כבר מופעל בתהליך אחר – דילוג.")
        return

    symbols = load_watchlist_symbols()
    logging.info(f"[main] Starting WebSocket for symbols: {symbols}")

    def runner():
        try:
            with open(WS_LOCK_PATH, "w") as f:
                f.write("active")
            logging.info("[main] WebSocket runner thread started")
            asyncio.run(launch_multi_websocket(symbols))
        except Exception as e:
            logging.error(f"[main] ❌ שגיאה בריצת WebSocket: {e}")
        finally:
            if os.path.exists(WS_LOCK_PATH):
                os.remove(WS_LOCK_PATH)
                logging.info("[main] WebSocket lock file removed")

    t = threading.Thread(target=runner, daemon=True)
    t.start()
    logging.info("[main] WebSocket background thread launched")

# === יצירת FastAPI ===
app = FastAPI(
    title="AlgoGPT API",
    description="API למסחר בזמן אמת ב-Binance (Futures, Spot, Grid, AI, SL/TP)",
    version="2.0.7"
)

# === קבצים סטטיים ===
if os.path.isdir(".well-known"):
    app.mount("/.well-known", StaticFiles(directory=".well-known"), name="well-known")
else:
    logging.info("ℹ️ התיקייה '.well-known' לא קיימת – mount לא בוצע.")

if os.path.isdir("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")
else:
    logging.info("ℹ️ התיקייה 'static' לא קיימת – mount לא בוצע.")

# === CORS ===
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# === ראוטים ===
from routes.ai import router as ai_router
from routes.trade import router as trade_router
from routes.grid import router as grid_router
from routes.multi_scan import router as multi_router
from auto_executor import start_executor, stop_executor, is_executor_running

app.include_router(ai_router)
app.include_router(trade_router)
app.include_router(grid_router)
app.include_router(multi_router)

# === אתחול רקע ===
@app.on_event("startup")
def startup_event():
    logging.info("[main] Server startup event triggered")
    start_ws_multi_background()

# === בדיקת חיים ===
@app.get("/healthz")
async def healthz():
    return {"status": "healthy ✅"}

# === ברירת מחדל ===
@app.get("/")
async def root():
    return {"status": "ok", "message": "AlgoGPT API is running ✅"}

# === שליטה ב־AutoExecutor ===
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

# === שליפת מחיר ===
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

# === ראוטים לבדיקה ===
@app.get("/debug/routes")
def get_routes():
    routes_info = [{"path": route.path, "name": route.name} for route in app.router.routes]
    logging.info(f"[debug] Registered routes: {routes_info}")
    return routes_info








