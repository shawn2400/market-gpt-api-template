# main.py
from __future__ import annotations

import os
import json
import time
import logging
from typing import Optional, List, Any, Dict

import httpx
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# =========================
# קונפיג כללי
# =========================
APP_VERSION = os.getenv("ALGOGPT_VERSION", "2.13.2")

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s: %(message)s",
)
logger = logging.getLogger("algogpt")

# =========================
# ייבוא אופציונלי של ליבת מסחר
# =========================
try:
    from trade_execution_core import dry_run_trade as _ext_dry_run_trade
except Exception:
    _ext_dry_run_trade = None

# =========================
# נרמול סימבולים
# =========================
from utils.symbols import normalize_symbol, SymbolsCache
symbols_cache = SymbolsCache(market="futures")

# =========================
# ניתוח סימבול / סורק
# =========================
try:
    # שומר תאימות לשם הקיים אצלך
    from utils.symbol_analysis import analyze_symbol
except Exception as e:
    analyze_symbol = None
    logger.warning("symbol_analysis not available: %s", e)

# לקבל נרות (DataFrame) לשכבות שונות
try:
    # אם יש לך utils/get_klines.py
    from utils.get_klines import get_klines
except Exception:
    # אחרת—ניקח מהקובץ החדש utils/klines.py
    from utils.klines import get_klines  # type: ignore


# =========================
# אבטחה פשוטה (Bearer חובה, בלי בדיקת ערך קשיח)
# אפשר להקשיח מול ENV בהמשך
# =========================
def auth_dep(request: Request):
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return True


# =========================
# סכימות (Pydantic) — תואמות OpenAPI שלך
# =========================
class TradeRequest(BaseModel):
    symbol: str = Field(example="BTCUSDT")
    side: str = Field(pattern="^(LONG|SHORT)$")
    entry: Optional[float] = Field(default=None, description="If null, live price is used")
    sl: Optional[float] = None
    tp: Optional[float] = None
    budget: Optional[float] = Field(default=100, gt=0)
    leverage: Optional[int] = Field(default=10, ge=1, le=125)


class TradeResponse(BaseModel):
    status: str
    result: Optional[dict] = None
    error: Optional[str] = None


class AiAnalyzeRequest(BaseModel):
    symbol: str
    rsi: float
    adx: float
    trend: str
    pattern: str
    volume: float


class AiAnalyzeResponse(BaseModel):
    symbol: str
    direction: str
    signal: str
    confidence: int
    reason: str
    frames: List[str]


class SLTPRequest(BaseModel):
    symbol: str
    direction: str = Field(pattern="^(LONG|SHORT)$")
    entry: float
    atr: Optional[float] = None


class SLTPResponse(BaseModel):
    symbol: str
    direction: str
    sl: float
    tp: float


class ScanResultItem(BaseModel):
    symbol: str
    quality_score: Optional[float] = None
    direction: Optional[str] = None
    trend: Optional[str] = None
    rsi: Optional[float] = None
    adx: Optional[float] = None
    volume: Optional[float] = None
    market: Optional[str] = None
    frames: Optional[List[str]] = None
    signal: Optional[str] = None
    confidence: Optional[int] = None
    reason: Optional[str] = None
    entry: Optional[float] = None
    atr: Optional[float] = None


class ScanResponse(BaseModel):
    results: List[ScanResultItem] = []


class PriceResponse(BaseModel):
    symbol: str
    price: float


class PnlPdfResponse(BaseModel):
    path: str


class GridTradeRequest(BaseModel):
    symbol: str
    budget: float = Field(gt=0)
    grid_count: int = Field(default=6, ge=2, le=50)
    grid_pct: float = Field(default=0.4, ge=0.01, le=5.0, description="Percent gap between levels")
    leverage: int = Field(default=20, ge=1, le=125)
    futures: bool = True
    tp_pct: float = Field(default=1.5, ge=0.01, le=10.0)
    sl_pct: float = Field(default=1.0, ge=0.01, le=10.0)


class GridTradeResponse(BaseModel):
    status: str
    reason: Optional[str] = None
    plan: Optional[dict] = None
    result: Optional[dict] = None
    error: Optional[str] = None


# =========================
# FastAPI init + CORS
# =========================
app = FastAPI(title="AlgoGPT API", version=APP_VERSION)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =========================
# עזרי Binance
# =========================
BINANCE_FAPI = "https://fapi.binance.com"
BINANCE_SPOT = "https://api.binance.com"


async def _get_mark_price(symbol: str) -> Optional[dict]:
    url = f"{BINANCE_FAPI}/fapi/v1/premiumIndex"
    async with httpx.AsyncClient(timeout=5.0) as x:
        r = await x.get(url, params={"symbol": symbol})
        r.raise_for_status()
        return r.json()


async def _get_exchange_info() -> Optional[dict]:
    url = f"{BINANCE_FAPI}/fapi/v1/exchangeInfo"
    async with httpx.AsyncClient(timeout=5.0) as x:
        r = await x.get(url)
        r.raise_for_status()
        return r.json()


# =========================
# Routes
# =========================
@app.get("/", tags=["Config"], summary="Root")
async def root():
    return {"status": "ok", "version": APP_VERSION}


@app.get("/health", tags=["Config"], summary="Health")
async def health():
    return {"status": "ok", "version": APP_VERSION}


@app.get("/net/ip", tags=["Config"], summary="Public egress IP (best-effort)")
async def get_egress_ip(request: Request):
    client_ip = None
    try:
        client_ip = request.client.host if request.client else None
    except Exception:
        client_ip = None

    egress = None
    for svc in ("https://api.ipify.org", "https://ifconfig.me/ip"):
        try:
            with httpx.Client(timeout=4.0) as x:
                resp = x.get(svc)
                if resp.status_code == 200:
                    egress = resp.text.strip()
                    break
        except Exception:
            pass
    return {"egress_ip": egress, "client_ip": client_ip}


@app.get("/scan/multi", tags=["Trades"], summary="Scan Multi", response_model=ScanResponse)
async def scan_multi(
    interval: str = "15m,1h",
    min_quality: int = 6,
    top: int = 10,
    market_type: str = "futures",
    trending_only: Optional[bool] = None,
    trending_source: str = "coingecko",
):
    """
    סריקה "לייט" כברירת־מחדל — על סל בסיסי כדי לא להעמיס.
    אפשר להרחיב בקלות בהמשך.
    """
    frames = [s.strip() for s in interval.split(",") if s.strip()]
    base_symbols = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"]

    results: List[ScanResultItem] = []

    if analyze_symbol is None:
        # אם מודול הניתוח לא קיים — נחזיר ריקים (לא שובר את הדוקס)
        return {"results": results}

    # נריץ על הסל (לייט). מי שירצה מלא — נשדרג לפר־exchangeInfo
    for sym in base_symbols:
        item_agg: Dict[str, Any] = {}
        best_quality = -1.0
        for tf in frames:
            try:
                res = await analyze_symbol(sym, market_type=market_type, interval=tf, limit=150, trending_only=bool(trending_only), frames=frames)
                if not res:
                    continue
                q = float(res.get("quality_score") or 0.0)
                if q > best_quality:
                    best_quality = q
                    item_agg = res
            except Exception as e:
                logger.warning("[scan] %s@%s: %s", sym, tf, e)
        if item_agg:
            if best_quality >= float(min_quality):
                results.append(ScanResultItem(**{
                    "symbol": item_agg.get("symbol"),
                    "quality_score": item_agg.get("quality_score"),
                    "direction": item_agg.get("direction"),
                    "trend": item_agg.get("trend"),
                    "rsi": item_agg.get("rsi"),
                    "adx": item_agg.get("adx"),
                    "volume": item_agg.get("volume"),
                    "market": item_agg.get("market"),
                    "frames": item_agg.get("frames"),
                    "signal": item_agg.get("signal"),
                    "confidence": item_agg.get("confidence"),
                    "reason": item_agg.get("reason"),
                    "entry": item_agg.get("indicators", {}).get("close"),
                    "atr": item_agg.get("indicators", {}).get("atr"),
                }))

    # מיון ו־top
    results.sort(key=lambda r: (r.quality_score or 0.0), reverse=True)
    results = results[:max(1, int(top))]
    return {"results": results}


@app.get("/price", tags=["Trades"], summary="Get Price", response_model=PriceResponse, dependencies=[Depends(auth_dep)])
async def get_price(symbol: str):
    try:
        sym = normalize_symbol(symbol, market="futures", cache=symbols_cache)
        data = await _get_mark_price(sym)
        price = float(data.get("markPrice"))
        return {"symbol": sym, "price": price}
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))


# פרמטרים "רכים" כפי שמופיע בלוג שלך
SLTP_MIN_PCT_FLOOR = float(os.getenv("SLTP_MIN_PCT_FLOOR", "0.0030"))   # 0.30%
SLTP_TP_PCT_FLOOR  = float(os.getenv("SLTP_TP_PCT_FLOOR",  "0.0060"))   # 0.60%
ATR_SL_MULT        = float(os.getenv("ATR_SL_MULT",        "1.50"))
ATR_TP_MULT        = float(os.getenv("ATR_TP_MULT",        "2.50"))

@app.post("/sltp", tags=["Trades"], summary="Suggest SL/TP", response_model=SLTPResponse, dependencies=[Depends(auth_dep)])
async def suggest_sltp(req: SLTPRequest):
    try:
        sym = normalize_symbol(req.symbol, market="futures", cache=symbols_cache)
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))

    # אם לא סופק ATR — ננסה משוער לפי אחוזי סף
    atr = float(req.atr) if req.atr is not None else max(req.entry * SLTP_MIN_PCT_FLOOR, 1.0)
    sl_dist = max(atr * ATR_SL_MULT, req.entry * SLTP_MIN_PCT_FLOOR)
    tp_dist = max(atr * ATR_TP_MULT, req.entry * SLTP_TP_PCT_FLOOR)

    if req.direction == "LONG":
        sl = round(req.entry - sl_dist, 2)
        tp = round(req.entry + tp_dist, 2)
    else:
        sl = round(req.entry + sl_dist, 2)
        tp = round(req.entry - tp_dist, 2)

    return {"symbol": sym, "direction": req.direction, "sl": sl, "tp": tp}


@app.post("/trade", tags=["Trades"], summary="Place Trade", response_model=TradeResponse, dependencies=[Depends(auth_dep)])
async def place_trade(req: TradeRequest):
    # נרמול סימבול (כולל 1000SHIBUSDT)
    try:
        req.symbol = normalize_symbol(req.symbol, market="futures", cache=symbols_cache)
    except Exception as e:
        return JSONResponse(status_code=422, content={"status": "error", "error": str(e), "result": None})

    # ליבת מסחר אופציונלית
    if _ext_dry_run_trade is None:
        return JSONResponse(status_code=501, content={"status": "error", "error": "trade core not installed", "result": None})

    try:
        # הליבה שלך אמורה להיות async; אם sync — עטיפה מתאימה
        result = await _ext_dry_run_trade(req.model_dump())
        return {"status": "success", "result": result}
    except Exception as e:
        logger.exception("trade failed")
        return JSONResponse(status_code=500, content={"status": "error", "error": str(e), "result": None})


@app.post("/ai-analyze", tags=["AI"], summary="AI analyze", response_model=AiAnalyzeResponse, dependencies=[Depends(auth_dep)])
async def ai_analyze(req: AiAnalyzeRequest):
    # לוגיקה קלה ועקבית לתגובה (לא מכביד; אפשר להחליף למודל חיצוני)
    t = (req.trend or "").upper()
    direction = "LONG" if t in ("UP", "BULL", "BULLISH", "LONG", "BUY") else ("SHORT" if t in ("DOWN", "BEAR", "BEARISH", "SHORT", "SELL") else "SIDEWAYS")
    # confidence גס לפי משתנים (דומה ל"light-scan")
    base = 50
    if req.adx >= 25: base += 10
    if direction != "SIDEWAYS": base += 10
    if req.rsi >= 55 and direction == "LONG": base += 10
    if req.rsi <= 45 and direction == "SHORT": base += 10
    confidence = max(0, min(100, base))
    signal = "HOLD"
    if direction == "LONG" and confidence >= 60: signal = "BUY"
    if direction == "SHORT" and confidence >= 60: signal = "SELL"
    reason = f"trend={t}, rsi={req.rsi}, adx={req.adx}"
    return AiAnalyzeResponse(symbol=req.symbol.upper(), direction=direction, signal=signal, confidence=confidence, reason=reason, frames=["15m","1h"])


# -------- Grid (DRY-RUN אם אין מודול ייעודי) ----------
try:
    from utils.binance_trader import binance_grid_trade  # type: ignore
except Exception:
    binance_grid_trade = None
    logger.info("[GRID] dedicated binance_grid_trade not available → using DRY-RUN grid executor")

@app.post("/grid/trade", tags=["Grid"], summary="Grid Trade", response_model=GridTradeResponse, dependencies=[Depends(auth_dep)])
async def execute_grid(req: GridTradeRequest):
    try:
        sym = normalize_symbol(req.symbol, market="futures", cache=symbols_cache)
    except Exception as e:
        return {"status": "error", "error": str(e)}

    # בניית תוכנית DRY-RUN קלה
    levels = [round(1.0 - (i * (req.grid_pct / 100.0)), 6) for i in range(req.grid_count)]
    plan = {
        "symbol": sym,
        "grid_count": req.grid_count,
        "grid_pct": req.grid_pct,
        "levels_mult": levels,
        "leverage": req.leverage,
        "futures": req.futures,
        "tp_pct": req.tp_pct,
        "sl_pct": req.sl_pct,
        "budget": req.budget,
    }

    if binance_grid_trade is None:
        return {"status": "dry_run", "plan": plan, "reason": "no dedicated grid executor"}

    try:
        # אם יש מודול — תריץ
        result = await binance_grid_trade(plan)
        return {"status": "success", "plan": plan, "result": result}
    except Exception as e:
        logger.exception("grid trade failed")
        return {"status": "error", "error": str(e), "plan": plan}


# -------- Executor (מצב בזיכרון בלבד) ----------
EXECUTOR_RUNNING = False

@app.get("/executor/start", tags=["Executor"], summary="Executor Start", dependencies=[Depends(auth_dep)])
async def start_executor():
    global EXECUTOR_RUNNING
    EXECUTOR_RUNNING = True
    return {"started": True, "running": EXECUTOR_RUNNING}

@app.get("/executor/stop", tags=["Executor"], summary="Executor Stop", dependencies=[Depends(auth_dep)])
async def stop_executor():
    global EXECUTOR_RUNNING
    EXECUTOR_RUNNING = False
    return {"stopped": True, "running": EXECUTOR_RUNNING}

@app.get("/executor/status", tags=["Executor"], summary="Executor Status", dependencies=[Depends(auth_dep)])
async def executor_status():
    return {"running": EXECUTOR_RUNNING}


# -------- PnL PDF (בשלב זה מחזיר 404 אם אין קובץ) ----------
@app.get("/report/pnl/pdf", tags=["Reports"], summary="Generate PnL PDF", response_model=PnlPdfResponse, dependencies=[Depends(auth_dep)])
async def generate_pnl_pdf():
    # אם אין נתונים — נחזיר 404 עקבי כמו שראית בלוגים
    raise HTTPException(status_code=404, detail="no PnL data")


# -------- Debug Binance Futures ----------
@app.get("/debug/binance-futures", tags=["Debug"], summary="Binance Futures connectivity", dependencies=[Depends(auth_dep)])
async def debug_binance_futures(symbol: str = "BTCUSDT", place_test: bool = False):
    out: Dict[str, Any] = {"ping_ok": False, "mark_price": None, "symbols_count": None, "permission_ok": None, "test_error": None}
    try:
        mp = await _get_mark_price(normalize_symbol(symbol, market="futures", cache=symbols_cache))
        out["mark_price"] = mp
        out["ping_ok"] = True
    except Exception as e:
        out["test_error"] = f"mark_price: {e}"

    try:
        exi = await _get_exchange_info()
        out["symbols_count"] = len(exi.get("symbols", [])) if exi else None
    except Exception as e:
        out["test_error"] = f"exchangeInfo: {e}"

    # בדיקת הרשאות פרטיות — לא שולחים הזמנה; אפשר להוסיף בדיקת balance אם יש keys
    if place_test:
        out["permission_ok"] = None  # לשמור התנהגות דומה למה שראית
    return out






















































