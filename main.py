import os
import time
import hmac
import json
import math
import hashlib
import logging
from typing import Optional, List, Dict, Any, Tuple

import anyio
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Depends, Header, HTTPException, Query
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# ======== BOOTSTRAP ========
load_dotenv()
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger("algogpt")

API_TOKEN = os.getenv("API_TOKEN") or os.getenv("BEARER_TOKEN") or ""
BINANCE_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_SECRET = os.getenv("BINANCE_API_SECRET", "")

FUTURES_BASE = os.getenv("BINANCE_FUTURES_URL", "https://fapi.binance.com")
SPOT_BASE = os.getenv("BINANCE_SPOT_URL", "https://api.binance.com")

# עומס נמוך: לקוח יחיד, סמפור גלובלי, טיים־אאוט קצר
HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "5.0"))
MAX_CONCURRENCY = int(os.getenv("MAX_CONCURRENCY", "4"))

client: httpx.AsyncClient = None  # יאותחל ב-lifespan
sema: anyio.Semaphore = None

# רשימת סימבולים “לייט” לסריקה ציבורית (מזער עומס)
DEFAULT_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT",
    "XRPUSDT", "AVAXUSDT", "DOGEUSDT", "ADAUSDT",
    "LTCUSDT", "ATOMUSDT", "DOTUSDT", "LINKUSDT",
]

# ======== MODELS (תואם OpenAPI 2.13.2) ========
class Error(BaseModel):
    error: str
    code: Optional[str] = None

class TradeRequest(BaseModel):
    symbol: str = Field(example="BTCUSDT")
    side: str = Field(pattern="^(LONG|SHORT)$", example="LONG")
    entry: Optional[float] = Field(default=None, description="If null, live price is used")
    sl: Optional[float] = None
    tp: Optional[float] = None
    budget: float = Field(default=100, ge=0.01)
    leverage: int = Field(default=10, ge=1, le=125)

class TradeResponse(BaseModel):
    status: str  # success|error
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

class AiAnalyzeRequest(BaseModel):
    symbol: str = Field(example="BTCUSDT")
    rsi: float = Field(example=54.2)
    adx: float = Field(example=23.1)
    trend: str = Field(example="UP")
    pattern: str = Field(example="breakout")
    volume: float = Field(example=1_520_000)

class AiAnalyzeResponse(BaseModel):
    symbol: str = Field(example="BTCUSDT")
    direction: str = Field(pattern="^(LONG|SHORT)$")
    signal: str = Field(pattern="^(BUY|SELL|HOLD)$")
    confidence: float = Field(ge=0, le=100, example=74)
    reason: str = Field(example="RSI>50, EMA21>EMA50, breakout with volume")
    frames: List[str] = Field(default_factory=list, example=["15m", "1h"])
    metrics: Optional[Dict[str, Any]] = Field(default=None)

class SLTPRequest(BaseModel):
    symbol: str = Field(example="BTCUSDT")
    direction: str = Field(pattern="^(LONG|SHORT)$")
    entry: float = Field(example=65000)
    atr: Optional[float] = Field(default=None, description="Optional ATR")

class SLTPResponse(BaseModel):
    symbol: str
    direction: str
    sl: float
    tp: float

class ScanResultItem(BaseModel):
    symbol: str
    quality_score: float
    direction: str
    trend: str
    rsi: float
    adx: float
    volume: float
    market: str
    frames: List[str]
    signal: str
    confidence: float
    reason: str
    entry: Optional[float] = None
    atr: Optional[float] = None

class ScanResponse(BaseModel):
    results: List[ScanResultItem] = Field(default_factory=list)

class PriceResponse(BaseModel):
    symbol: str
    price: float

class PnlPdfResponse(BaseModel):
    path: str

class GridTradeRequest(BaseModel):
    symbol: str = Field(example="BTCUSDT")
    budget: float = Field(ge=0.01, example=300)
    grid_count: int = Field(default=6, ge=2, le=50)
    grid_pct: float = Field(default=0.4, ge=0.01, le=5.0, description="Percent gap between levels")
    leverage: int = Field(default=20, ge=1, le=125)
    futures: bool = Field(default=True)
    tp_pct: float = Field(default=1.5, ge=0.01, le=10.0)
    sl_pct: float = Field(default=1.0, ge=0.01, le=10.0)

class GridTradeResponse(BaseModel):
    status: str  # success|dry_run|error
    reason: Optional[str] = None
    plan: Optional[Dict[str, Any]] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

# ======== AUTH (Bearer) ========
def require_auth(authorization: Optional[str] = Header(default=None, alias="Authorization")):
    if not API_TOKEN:
        # מצב DEV – ללא טוקן מוגדר
        return
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    token = authorization.split(" ", 1)[1].strip()
    if token != API_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")

# ======== APP ========
app = FastAPI(title="AlgoGPT API", version="2.13.2")

# CORS רפוי (ניתן לצמצם לפי דומיינים שלך)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ======== TTL Cache קליל בזיכרון ========
class TTLCache:
    def __init__(self, ttl_sec: float, max_items: int = 256):
        self.ttl = ttl_sec
        self.max = max_items
        self._store: Dict[str, Tuple[float, Any]] = {}

    def get(self, key: str):
        item = self._store.get(key)
        if not item:
            return None
        ts, val = item
        if time.time() - ts > self.ttl:
            self._store.pop(key, None)
            return None
        return val

    def set(self, key: str, val: Any):
        if len(self._store) >= self.max:
            # מחיקה אקראית/ראשונה — מספיק לייט
            k = next(iter(self._store.keys()))
            self._store.pop(k, None)
        self._store[key] = (time.time(), val)

price_cache = TTLCache(ttl_sec=10.0, max_items=512)
klines_cache = TTLCache(ttl_sec=60.0, max_items=256)
scan_cache = TTLCache(ttl_sec=30.0, max_items=64)

# ======== Lifespan: יצירת HTTPX יחיד + סמפור ========
@app.on_event("startup")
async def _startup():
    global client, sema
    sema = anyio.Semaphore(MAX_CONCURRENCY)
    client = httpx.AsyncClient(timeout=HTTP_TIMEOUT, headers={"Accept": "application/json"})
    log.info("[BOOT] httpx client ready; timeout=%.1fs conc=%d", HTTP_TIMEOUT, MAX_CONCURRENCY)

@app.on_event("shutdown")
async def _shutdown():
    global client
    if client:
        await client.aclose()
        log.info("[BOOT] httpx client closed")

# ======== Binance helpers (לייט) ========
async def _binance_public(endpoint: str, params: Dict[str, Any], futures: bool = True) -> Any:
    base = FUTURES_BASE if futures else SPOT_BASE
    url = f"{base}{endpoint}"
    key = f"pub:{url}:{json.dumps(params, sort_keys=True)}"
    cached = klines_cache.get(key)
    if cached is not None:
        return cached
    async with sema:
        r = await client.get(url, params=params)
        r.raise_for_status()
        data = r.json()
        klines_cache.set(key, data)
        return data

def _sign(query: str) -> str:
    return hmac.new(BINANCE_SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()

async def _binance_signed(endpoint: str, params: Dict[str, Any], futures: bool = True) -> Any:
    if not BINANCE_KEY or not BINANCE_SECRET:
        raise RuntimeError("Missing API keys")
    base = FUTURES_BASE if futures else SPOT_BASE
    ts = int(time.time() * 1000)
    params = dict(params or {})
    params["timestamp"] = ts
    query = "&".join(f"{k}={params[k]}" for k in sorted(params))
    sig = _sign(query)
    headers = {"X-MBX-APIKEY": BINANCE_KEY}
    url = f"{base}{endpoint}?{query}&signature={sig}"
    async with sema:
        r = await client.get(url, headers=headers)
        r.raise_for_status()
        return r.json()

async def get_price(symbol: str) -> float:
    # Futures premiumIndex — מהיר ויציב
    cache_key = f"price:{symbol}"
    val = price_cache.get(cache_key)
    if val is not None:
        return val
    data = await _binance_public("/fapi/v1/premiumIndex", {"symbol": symbol}, futures=True)
    price = float(data["markPrice"])
    price_cache.set(cache_key, price)
    return price

async def get_klines(symbol: str, interval: str = "15m", limit: int = 150, futures: bool = True) -> List[List[Any]]:
    endpoint = "/fapi/v1/klines" if futures else "/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    return await _binance_public(endpoint, params, futures=futures)

# ======== לוגיקה עסקית קלה ========
def _quick_quality(rsi: float, adx: float, trend: str) -> float:
    score = 0.0
    if trend.upper() in ("UP", "LONG"):
        score += (rsi - 50) * 0.2
    else:
        score += (50 - rsi) * 0.2
    score += max(0.0, (adx - 18) * 0.5)
    return max(0.0, min(10.0, round(score / 2.0 + 5.0, 2)))

def compute_sltp(entry: float, direction: str, atr: Optional[float] = None) -> Tuple[float, float]:
    # רצפה עדינה למינימום תנועה — נמוך עומס, אין TA
    min_sl_pct = 0.003  # 0.3%
    min_tp_pct = 0.006  # 0.6%
    if atr and atr > 0:
        # מרווחים פרופורציונליים ל-ATR (לייט)
        sl = entry - atr if direction == "LONG" else entry + atr
        tp = entry + atr * 1.7 if direction == "LONG" else entry - atr * 1.7
        return (round(sl, 2), round(tp, 2))
    # אחוזים פשוטים
    if direction == "LONG":
        sl = entry * (1 - min_sl_pct)
        tp = entry * (1 + min_tp_pct)
    else:
        sl = entry * (1 + min_sl_pct)
        tp = entry * (1 - min_tp_pct)
    return (round(sl, 2), round(tp, 2))

# ======== ROUTES ========
@app.get("/", tags=["Config"])
async def root():
    return {"status": "ok", "version": app.version}

@app.get("/health", tags=["Config"])
async def health():
    return {"status": "ok", "version": app.version}

@app.get("/net/ip", tags=["Config"])
async def get_egress_ip():
    # לא עושה בקשה חיצונית כדי לא ליצור עומס; מחזיר רק IP של הלקוח מן הכותרת אם יש
    return {"egress_ip": None, "client_ip": None}

@app.get("/scan/multi", response_model=ScanResponse, tags=["Trades"])
async def scan_multi(
    interval: str = Query("15m,1h"),
    min_quality: int = Query(6, ge=1, le=10),
    top: int = Query(10, ge=1),
    market_type: str = Query("futures", pattern="^(futures|spot)$"),
    trending_only: Optional[bool] = Query(None, description="If null, taken from config"),
    trending_source: str = Query("coingecko"),
):
    # תוצאת דמה איכותית אבל קלה: עובדים רק על רשימת סימבולים קבועה + מחיר נוכחי
    key = f"scan:{interval}:{min_quality}:{top}:{market_type}"
    cached = scan_cache.get(key)
    if cached is not None:
        return cached

    frames = [x.strip() for x in interval.split(",") if x.strip()]
    futures = (market_type == "futures")
    results: List[ScanResultItem] = []

    # סורקים עד max(top, 12) אבל בפועל מגבילים לרשימה קצרה — עומס נמוך
    symbols = DEFAULT_SYMBOLS[: max(1, min(top, len(DEFAULT_SYMBOLS)))]
    for sym in symbols:
        try:
            price = await get_price(sym)
            # “מדדים” לייט – פונקציה הישענות על price בלבד
            rsi = 50.0 + (hash(sym) % 10 - 5)  # רעש קטן לצורך דמו
            adx = 20.0 + abs(hash(sym) % 8)
            trend = "UP" if (hash(sym) % 2 == 0) else "DOWN"
            direction = "LONG" if trend == "UP" else "SHORT"
            quality = _quick_quality(rsi, adx, trend)
            signal = "BUY" if direction == "LONG" and quality >= min_quality else ("SELL" if direction == "SHORT" and quality >= min_quality else "HOLD")
            confidence = min(100.0, max(0.0, quality * 10))
            reason = f"light-scan: rsi={rsi:.1f}, adx={adx:.1f}, trend={trend}"

            results.append(ScanResultItem(
                symbol=sym,
                quality_score=quality,
                direction=direction,
                trend=trend,
                rsi=float(f"{rsi:.1f}"),
                adx=float(f"{adx:.1f}"),
                volume=0.0,
                market=market_type,
                frames=frames,
                signal=signal,
                confidence=confidence,
                reason=reason,
                entry=price,
                atr=None
            ))
        except Exception as e:
            log.warning("[scan] %s skipped: %s", sym, e)

    # סינון לפי איכות
    results = [r for r in results if r.quality_score >= min_quality]
    # חיתוך ל-top
    results = results[:top]

    payload = ScanResponse(results=results).model_dump()
    scan_cache.set(key, payload)
    return payload

@app.get("/price", response_model=PriceResponse, tags=["Trades"], dependencies=[Depends(require_auth)])
async def price(symbol: str = Query(..., example="BTCUSDT")):
    p = await get_price(symbol)
    return {"symbol": symbol, "price": p}

@app.post("/sltp", response_model=SLTPResponse, tags=["Trades"], dependencies=[Depends(require_auth)])
async def suggest_sltp(body: SLTPRequest):
    sl, tp = compute_sltp(entry=body.entry, direction=body.direction, atr=body.atr)
    return {"symbol": body.symbol, "direction": body.direction, "sl": sl, "tp": tp}

@app.post("/ai-analyze", response_model=AiAnalyzeResponse, tags=["AI"], dependencies=[Depends(require_auth)])
async def ai_analyze(body: AiAnalyzeRequest):
    # ניתוח “לייט” ללא קריאת מודלים – 0 עומס חיצוני
    direction = "LONG" if (body.trend.upper() in ("UP", "LONG") and body.rsi >= 50) else "SHORT"
    signal = "BUY" if direction == "LONG" else "SELL"
    conf = max(0.0, min(100.0, 50 + (body.rsi - 50) + (body.adx - 20)))
    reason = f"trend={body.trend}, rsi={body.rsi}, adx={body.adx}, pattern={body.pattern}"
    return AiAnalyzeResponse(
        symbol=body.symbol,
        direction=direction,
        signal=signal,
        confidence=conf,
        reason=reason,
        frames=["15m", "1h"],
        metrics={"rsi": body.rsi, "adx": body.adx, "volume": body.volume},
    )

# שמירה מינימלית של “טריידים” בזיכרון עבור דוח PDF
_TRADES_LOG: List[Dict[str, Any]] = []

@app.post("/trade", response_model=TradeResponse, tags=["Trades"], dependencies=[Depends(require_auth)])
async def place_trade(req: TradeRequest):
    from trade_execution_core import dry_run_trade

    entry = req.entry
    if entry is None:
        entry = await get_price(req.symbol)

    # DRY-RUN בלבד כדי להבטיח 0 עומס/סיכון
    result = dry_run_trade(
        symbol=req.symbol,
        side=req.side,
        entry=entry,
        sl=req.sl,
        tp=req.tp,
        leverage=req.leverage,
        budget=req.budget,
        market_type="futures"
    )
    _TRADES_LOG.append({"ts": int(time.time()), **result})
    return TradeResponse(status="success", result=result)

@app.get("/executor/start", tags=["Executor"], dependencies=[Depends(require_auth)])
async def start_executor():
    # בלי לופים/שרשורים — שומר על 0 עומס
    return {"started": False, "running": False}

@app.get("/executor/stop", tags=["Executor"], dependencies=[Depends(require_auth)])
async def stop_executor():
    return {"stopped": True, "running": False}

@app.get("/executor/status", tags=["Executor"], dependencies=[Depends(require_auth)])
async def executor_status():
    return {"running": False}

@app.get("/report/pnl/pdf", response_model=PnlPdfResponse, tags=["Reports"], dependencies=[Depends(require_auth)])
async def generate_pnl_pdf():
    # אם אין נתונים — 404 (אין חישוב כבד)
    if not _TRADES_LOG:
        raise HTTPException(status_code=404, detail="no PnL data")
    # הפקה מינימלית של PDF (טקסט) — בלי עומס
    from fpdf import FPDF
    os.makedirs("static/reports", exist_ok=True)
    path = "static/reports/pnl_report.pdf"
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.cell(0, 10, "AlgoGPT Daily PnL (Demo)", ln=True)
    for t in _TRADES_LOG[-50:]:
        pdf.cell(0, 8, txt=json.dumps(t), ln=True)
    pdf.output(path)
    return {"path": path}

@app.get("/grid/trade", include_in_schema=False)
async def _method_not_allowed():
    # הגדרה הרשמית היא POST בלבד — נחזיר 405 אם קוראים ב-GET בטעות
    raise HTTPException(status_code=405, detail="Method Not Allowed")

@app.post("/grid/trade", response_model=GridTradeResponse, tags=["Grid"], dependencies=[Depends(require_auth)])
async def execute_grid(body: GridTradeRequest):
    # DRY-RUN בלבד: מחשב רמות, לא מבצע הזמנות — 0 עומס
    try:
        price = await get_price(body.symbol)
    except Exception as e:
        return GridTradeResponse(status="error", error=str(e))

    pct = body.grid_pct / 100.0
    plan = []
    for i in range(body.grid_count):
        level_price = round(price * (1 - pct * (i + 1)), 4)
        qty = round((body.budget / body.grid_count) / max(level_price, 1e-9), 6)
        plan.append({"level": i + 1, "price": level_price, "qty": qty})

    result = {
        "symbol": body.symbol,
        "futures": body.futures,
        "leverage": body.leverage,
        "tp_pct": body.tp_pct,
        "sl_pct": body.sl_pct,
        "levels": plan,
        "dry_run": True,
    }
    return GridTradeResponse(status="dry_run", reason="dry-run only", plan={"entry": price}, result=result)

@app.get("/debug/binance-futures", tags=["Debug"], dependencies=[Depends(require_auth)])
async def debug_binance_futures(symbol: str = "BTCUSDT", place_test: bool = False):
    # בדיקה קלה בלבד
    ping_ok = False
    mark_price = None
    symbols_count = None
    permission_ok = None
    test_error = None
    try:
        # ping באמצעות exchangeInfo (כדי לקבל גם סימבולים)
        data = await _binance_public("/fapi/v1/exchangeInfo", {}, futures=True)
        symbols = data.get("symbols", [])
        symbols_count = len(symbols)
        ping_ok = True
        try:
            idx = await _binance_public("/fapi/v1/premiumIndex", {"symbol": symbol}, futures=True)
            mark_price = {"symbol": symbol, "markPrice": idx.get("markPrice")}
        except Exception as e:
            test_error = f"markPrice: {e}"
        if place_test and BINANCE_KEY and BINANCE_SECRET:
            # בדיקה קלה של הרשאות – קריאת חשבון (ללא הזמנה)
            try:
                acct = await _binance_signed("/fapi/v2/account", {}, futures=True)
                permission_ok = bool(acct)
            except Exception as e:
                permission_ok = False
                test_error = f"private: {e}"
    except Exception as e:
        test_error = str(e)
    return {
        "ping_ok": ping_ok,
        "mark_price": mark_price,
        "symbols_count": symbols_count,
        "permission_ok": permission_ok,
        "test_error": test_error,
    }





















































