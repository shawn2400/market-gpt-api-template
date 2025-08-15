# main.py
from __future__ import annotations

import os
import logging
from typing import Optional, List, Any, Dict

import httpx
from fastapi import FastAPI, Depends, HTTPException, Request, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

APP_VERSION = os.getenv("ALGOGPT_VERSION", "2.13.3")

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s: %(message)s",
)
logger = logging.getLogger("algogpt")

# --- סימבולים / נרמול ---
from utils.symbols import normalize_symbol, SymbolsCache
symbols_cache = SymbolsCache(market="futures")

# --- סורק / AI / עוגן / קווים ---
from utils.btc_anchor import compute_btc_anchor, anchor_gate, sltp_multipliers
from utils.ai_analysis import analyze_with_ai, predict_optimal_sl_tp
from utils.multi_tf_scanner import multi_tf_scan_with_ai, fallback_scan_manual
from utils.binance_client import ping_and_info, get_client
from utils.ai_client import ai_healthcheck

# --- klines (פומבי) ---
BINANCE_FAPI = "https://fapi.binance.com"

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

# --- אימות טוקן (מקבל Authorization: Bearer / X-API-Key / ?token) ---
API_BEARER_TOKEN = os.getenv("API_BEARER_TOKEN", "").strip()

def auth_dep(
    authorization: str = Header(default=""),
    x_api_key: str = Header(default=""),
    token: str = Query(default="")
):
    """
    אם מוגדר API_BEARER_TOKEN → חייבים התאמה.
    אם לא מוגדר → עדיין דורשים כל טוקן (Bearer/X-API-Key/?token) כדי למנוע שימוש אנונימי.
    """
    bearer = ""
    if authorization.lower().startswith("bearer "):
        bearer = authorization.split(" ", 1)[1].strip()
    if not bearer:
        bearer = (x_api_key or token or "").strip()

    if API_BEARER_TOKEN:
        if bearer != API_BEARER_TOKEN:
            raise HTTPException(status_code=401, detail="Unauthorized")
    else:
        if not bearer:
            raise HTTPException(status_code=401, detail="Unauthorized")
    return True

# --- סכימות ---
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
    metrics: Optional[dict] = None

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
    results: List[ScanResultItem] = Field(default_factory=list)

class PriceResponse(BaseModel):
    symbol: str
    price: float

class PnlPdfResponse(BaseModel):
    path: str

class GridTradeRequest(BaseModel):
    symbol: str
    budget: float = Field(gt=0)
    grid_count: int = Field(default=6, ge=2, le=50)
    grid_pct: float = Field(default=0.4, ge=0.01, le=5.0)
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

# --- FastAPI ---
app = FastAPI(title="AlgoGPT API", version=APP_VERSION)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

# --- Startup / Shutdown (אופציונלי) ---
try:
    from utils.ai_client import ai_client as _ai_client
except Exception:
    _ai_client = None

@app.on_event("startup")
async def _on_startup():
    if _ai_client is not None:
        try:
            await _ai_client.warmup()
            logger.info("[BOOT] AI client warmup done (ready=%s)", getattr(_ai_client, "ready", False))
        except Exception as e:
            logger.warning("[BOOT] AI warmup failed: %s", e)

@app.on_event("shutdown")
async def _on_shutdown():
    if _ai_client is not None:
        try:
            await _ai_client.close()
        except Exception:
            pass

# -------- Root / Health --------
@app.get("/", tags=["Config"], summary="Root")
async def root():
    return {"status": "ok", "version": APP_VERSION}

@app.get("/health", tags=["Config"], summary="Health")
async def health():
    return {"status": "ok", "version": APP_VERSION}

# בריאות מלאה (Binance/AI/ENV/Files)
CRITICAL_FILES = ["watchlist.json", "open_trades.json", "pnl_tracker.json"]
REQUIRED_ENV   = ["BINANCE_API_KEY", "BINANCE_API_SECRET", "OPENAI_API_KEY"]

def _files_status() -> Dict[str, Any]:
    import json, os
    details = []
    ok = True
    for f in CRITICAL_FILES:
        exists = os.path.exists(f)
        size = os.path.getsize(f) if exists else 0
        readable = False
        if exists:
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    json.load(fh)
                readable = True
            except Exception:
                ok = False
        else:
            ok = False
        details.append({"file": f, "exists": exists, "readable_json": readable, "size": size})
    return {"ok": ok, "details": details}

@app.get("/health/full", tags=["Config"], summary="Full system health", dependencies=[Depends(auth_dep)])
async def health_full():
    # Binance public
    try:
        binance_ping = bool(ping_and_info())
    except Exception:
        binance_ping = False

    # Binance private (אופציונלי)
    binance_private = None
    if os.getenv("BINANCE_API_KEY") and os.getenv("BINANCE_API_SECRET"):
        try:
            client = get_client()
            # קריאה קלה שדורשת חתימה
            await app.state.loop.run_in_executor(None, client.futures_account_balance)  # type: ignore
            binance_private = True
        except Exception:
            binance_private = False

    # AI
    try:
        ai = await ai_healthcheck()
    except Exception as e:
        ai = {"ok": False, "error": str(e)}

    files = _files_status()
    missing_env = [k for k in REQUIRED_ENV if not os.getenv(k)]
    envs = {"ok": len(missing_env) == 0, "missing": missing_env}
    ok = binance_ping and (ai.get("ok") is True) and files["ok"]

    return {
        "ok": ok,
        "binance": {"ping_ok": binance_ping, "private_ok": binance_private},
        "ai": ai,
        "env": envs,
        "files": files,
        "version": APP_VERSION,
    }

# -------- Scanner --------
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
    עטיפה קשיחה סביב multi_tf_scan_with_ai עם fallback ידני (אף פעם לא 500).
    """
    try:
        tfs = tuple([s.strip() for s in interval.split(",") if s.strip()])
        results = await multi_tf_scan_with_ai(
            timeframes=tfs or ("15m", "1h"),
            markets=(market_type,),
            min_quality=min_quality,
            top=top,
            trending_only=bool(trending_only),
            trending_source=trending_source,
        )
        if not results:
            # fallback "בטוח"
            return {"results": await fallback_scan_manual("BTCUSDT")}
        return {"results": results}
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("[scan/multi] fallback due to: %s", e)
        try:
            fb = await fallback_scan_manual("BTCUSDT")
            return {"results": fb}
        except Exception as e2:
            # אפילו בפולבק לא מפילים שרת
            return {"results": [], "error": f"{e} / fallback: {e2}"}

# -------- Price (מוגן) --------
@app.get("/price", tags=["Trades"], summary="Get Price",
         response_model=PriceResponse, dependencies=[Depends(auth_dep)])
async def get_price(symbol: str):
    try:
        sym = normalize_symbol(symbol, market="futures", cache=symbols_cache)
        data = await _get_mark_price(sym)
        price = float(data.get("markPrice"))
        return {"symbol": sym, "price": price}
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))

# -------- SLTP (מוגן) --------
SLTP_MIN_PCT_FLOOR = float(os.getenv("SLTP_MIN_PCT_FLOOR", "0.0030"))
SLTP_TP_PCT_FLOOR  = float(os.getenv("SLTP_TP_PCT_FLOOR",  "0.0060"))
ATR_SL_MULT        = float(os.getenv("ATR_SL_MULT",        "1.50"))
ATR_TP_MULT        = float(os.getenv("ATR_TP_MULT",        "2.50"))

@app.post("/sltp", tags=["Trades"], summary="Suggest SL/TP",
          response_model=SLTPResponse, dependencies=[Depends(auth_dep)])
async def suggest_sltp(req: SLTPRequest):
    try:
        sym = normalize_symbol(req.symbol, market="futures", cache=symbols_cache)
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))
    atr = float(req.atr) if req.atr is not None else max(req.entry * SLTP_MIN_PCT_FLOOR, 1.0)
    base_sl = max(atr * ATR_SL_MULT, req.entry * SLTP_MIN_PCT_FLOOR)
    base_tp = max(atr * ATR_TP_MULT, req.entry * SLTP_TP_PCT_FLOOR)

    anchor = await compute_btc_anchor(frames=["15m", "1h"], market="futures")
    sl_mult, tp_mult = sltp_multipliers(req.direction, anchor, strong_th=70, weak_th=55)
    sl_dist = base_sl * sl_mult
    tp_dist = base_tp * tp_mult

    if req.direction == "LONG":
        sl = round(req.entry - sl_dist, 6)
        tp = round(req.entry + tp_dist, 6)
    else:
        sl = round(req.entry + sl_dist, 6)
        tp = round(req.entry - tp_dist, 6)
    return {"symbol": sym, "direction": req.direction, "sl": sl, "tp": tp}

# -------- AI analyze (מוגן) --------
def _norm_direction_from_trend(trend: str) -> str:
    t = (trend or "").strip().lower()
    if t in ("up", "long", "buy", "bull", "bullish"): return "LONG"
    if t in ("down", "short", "sell", "bear", "bearish"): return "SHORT"
    return "SIDEWAYS"

@app.post("/ai-analyze", tags=["AI"], summary="Manual AI analysis",
          response_model=AiAnalyzeResponse, dependencies=[Depends(auth_dep)])
async def ai_analyze(req: AiAnalyzeRequest):
    frames = ["manual"]
    direction = _norm_direction_from_trend(req.trend)
    tf_item = {
        "symbol": req.symbol.upper(),
        "interval": "manual",
        "indicators": {"rsi": req.rsi, "adx": req.adx, "close": None},
        "trend": req.trend.upper(),
        "direction": direction,
        "volume": req.volume,
        "pattern": req.pattern,
        "quality_score": max(0.0, min(10.0, (req.adx / 5.0) + (max(0.0, req.rsi - 50.0) / 10.0))),
        "frames": frames,
    }
    try:
        ai_res = await analyze_with_ai([tf_item])
    except Exception:
        ai_res = {}
    anchor = await compute_btc_anchor(frames=["15m", "1h"], market="futures")
    reason = (ai_res.get("reason") or "").strip()
    reason = (reason + f"; anchor={anchor.get('direction')}/{anchor.get('strength')}").strip("; ")
    return AiAnalyzeResponse(
        symbol=req.symbol.upper(),
        direction=direction,
        signal=(ai_res.get("signal") or "HOLD"),
        confidence=int(ai_res.get("confidence") or 50),
        reason=reason or f"trend={req.trend} rsi={req.rsi} adx={req.adx}; anchor={anchor.get('direction')}/{anchor.get('strength')}",
        frames=frames,
        metrics={"rsi": req.rsi, "adx": req.adx, "volume": req.volume, "pattern": req.pattern},
    )

# -------- Trade (מוגן + Gate) --------
@app.post("/trade", tags=["Trades"], summary="Place Trade",
          response_model=TradeResponse, dependencies=[Depends(auth_dep)])
async def place_trade(req: TradeRequest):
    try:
        req.symbol = normalize_symbol(req.symbol, market="futures", cache=symbols_cache)
    except Exception as e:
        return JSONResponse(status_code=422, content={"status": "error", "error": str(e), "result": None})

    anchor = await compute_btc_anchor(frames=["15m", "1h"], market="futures")
    gate = anchor_gate(req.side, anchor, strong_th=70, weak_th=55)
    if gate["action"] == "block":
        return JSONResponse(status_code=409, content={
            "status": "error",
            "error": f"blocked by BTC anchor: {gate['reason']}",
            "result": None
        })

    # placeholder ל-core חיצוני אם קיים
    try:
        from trade_execution_core import dry_run_trade as _ext_dry_run_trade
    except Exception:
        _ext_dry_run_trade = None

    if _ext_dry_run_trade is None:
        return JSONResponse(status_code=501, content={"status": "error", "error": "trade core not installed", "result": None})

    try:
        result = await _ext_dry_run_trade(req.model_dump())  # type: ignore
        return {"status": "success", "result": result}
    except Exception as e:
        logger.exception("trade failed")
        return JSONResponse(status_code=500, content={"status": "error", "error": str(e), "result": None})

# -------- Executor (in-mem demo, מוגן) --------
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

# אליאס תאימות לאחור:
@app.get("/auto-executor/status", tags=["Executor"], summary="Executor Status (alias)", dependencies=[Depends(auth_dep)])
async def auto_executor_status():
    return {"running": EXECUTOR_RUNNING}

# -------- Reports (placeholder מוגן) --------
@app.get("/report/pnl/pdf", tags=["Reports"], summary="Generate PnL PDF",
         response_model=PnlPdfResponse, dependencies=[Depends(auth_dep)])
async def generate_pnl_pdf():
    raise HTTPException(status_code=404, detail="no PnL data")

# -------- Debug Futures (מוגן) --------
@app.get("/debug/binance-futures", tags=["Debug"], summary="Binance Futures connectivity", dependencies=[Depends(auth_dep)])
async def debug_binance_futures(symbol: str = "BTCUSDT", place_test: bool = False):
    out: Dict[str, Any] = {
        "ping_ok": False, "mark_price": None, "symbols_count": None,
        "permission_ok": None, "test_error": None
    }
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

    if place_test:
        # כאן אפשר להוסיף קריאת TEST חתומה אם תרצה
        out["permission_ok"] = None
    return out
























































































































