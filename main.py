import os
import json
import logging
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
from utils.ws_fallback import launch_multi_websocket, get_price
from auto_executor import start_executor, stop_executor, is_executor_running

# === טעינת ENV ===
load_dotenv()

# === הגדרת לוגים מפורטים ===
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(message)s',
    force=True
)

# === קריאת מפתחות והגדרות ===
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MAX_WS_SYMBOLS = int(os.getenv("MAX_WS_SYMBOLS", 15))  # ברירת מחדל 15

logging.info(f"[ENV] Binance API Key Loaded: {'Yes' if BINANCE_API_KEY else 'No'}")
logging.info(f"[ENV] Binance API Secret Loaded: {'Yes' if BINANCE_API_SECRET else 'No'}")
logging.info(f"[ENV] OpenAI API Key Loaded: {'Yes' if OPENAI_API_KEY else 'No'}")
logging.info(f"[ENV] Max WS Symbols: {MAX_WS_SYMBOLS}")

# === קריאת רשימת מעקב עם חיתוך לפי הגבלה ===
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

app.include_router(ai_router)
app.include_router(trade_router)
app.include_router(grid_router)
app.include_router(multi_router)

# === אתחול WebSocket אסינכרוני ב־startup ===
@app.on_event("startup")
async def startup_event():
    logging.info("[main] Server startup event triggered")
    symbols = load_watchlist_symbols()
    await launch_multi_websocket(symbols)
    logging.info(f"[main] WebSocket started for symbols: {symbols}")

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













