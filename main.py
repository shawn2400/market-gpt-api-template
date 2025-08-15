# main.py
from __future__ import annotations

import os
import logging
from typing import Optional, List, Any, Dict

import httpx
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

APP_VERSION = os.getenv("ALGOGPT_VERSION", "2.13.3")

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s: %(message)s",
)
logger = logging.getLogger("algogpt")

# --- ליבת מסחר (אם מותקן) ---
try:
    from trade_execution_core import dry_run_trade as _ext_dry_run_trade
except Exception:
    _ext_dry_run_trade = None

# --- סימבולים / נרמול ---
from utils.symbols import normalize_symbol, SymbolsCache
symbols_cache = SymbolsCache(market="futures")

# --- סורק סימבול ---
try:
    from utils.symbol_analysis import analyze_symbol
except Exception as e:
    analyze_symbol = None
    logger.warning("symbol_analysis not available: %s", e)

# --- klines ---
try:
    from utils.get_klines import get_klines
except Exception:
    from utils.klines import get_klines  # type: ignore

# --- עוגן BTC ---
from utils.btc_anchor import compute_btc_anchor, anchor_gate, sltp_multipliers

# --- AI (לניתוח ידני/SLTP חכם) ---
try:
    from utils.ai_analysis import analyze_with_ai, predict_optimal_sl_tp
except Exception:
    analyze_with_ai = None
    predict_optimal_sl_tp = None

# AI client לאירועי startup/shutdown (אופציונלי)
try:
    from utils.ai_client import ai_client as _ai_client
except Exception:
    _ai_client = None

# --- קונפיג לעוגן ---
ANCHOR_ENFORCE = os.getenv("BTC_ANCHOR_ENFORCE", "true").lower() == "true"
ANCHOR_STRONG_TH = int(os.getenv("BTC_ANCHOR_STRONG_TH", "70"))
ANCHOR_WEAK_TH   = int(os.getenv("BTC_ANCHOR_WEAK_TH",   "55"))

# --- אימות טוקן (פרטי) ---
API_BEARER_TOKEN = os.getenv("API_BEARER_TOKEN", "").strip()

def auth_dep(request: Request):
    """
    אימות פשוט:
    - אם מוגדר API_BEARER_TOKEN בסביבה → חייבים להתאים בדיוק.
    - אם לא מוגדר → עדיין דורשים טוקן (Header Authorization: Bearer XXX או ?token=XXX),
      אבל לא בודקים ערך ספציפי. מתאים לפרטי/שימוש פנימי.
    """
    auth = request.headers.get("Authorization", "")
    bearer = ""
    if auth.lower().startswith("bearer "):
        bearer = auth.split(" ", 1)[1].strip()
    if not bearer:
        qtok = request.query_params.get("token")
        if qtok:
            bearer = qtok.strip()

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

# --- FastAPI ---
app = FastAPI(title="AlgoGPT API", version=APP_VERSION)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

# הגשת סטטיים (ל־PDF, לוגו וכו')
app.mount("/static", StaticFiles(directory="static"), name="static")

# --- Startup / Shutdown ---
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
            logger.info("[BOOT] httpx client closed")
        except Exception:
            pass

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

# -------- Config routes --------
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

# -------- Anchor debug --------
@app.get("/anchor/btc", tags=["Debug"], summary="Current BTC anchor (cached)")
async def get_btc_anchor(frames: str = "15m,1h", market: str = "futures"):
    fr = [s.strip() for s in frames.split(",") if s.strip()]
    return await compute_btc_anchor(frames=fr, market=market)

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
    frames = [s.strip() for s in interval.split(",") if s.strip()]
    base_symbols = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"]

    anchor = await compute_btc_anchor(frames=frames, market=market_type)

    results: List[ScanResultItem] = []
    if analyze_symbol is None:
        return {"results": results}

    for sym in base_symbols:
        item_agg: Dict[str, Any] = {}
        best_quality = -1.0
        for tf in frames:
            try:
                res = await analyze_symbol(
                    sym, market_type=market_type, interval=tf,
                    limit=150, trending_only=bool(trending_only),
                    frames=frames, btc_anchor=anchor
                )
                if not res:
                    continue
                q = float(res.get("quality_score") or 0.0)
                if q > best_quality:
                    best_quality = q
                    item_agg = res
            except Exception as e:
                logger.warning("[scan] %s@%s: %s", sym, tf, e)

        if not item_agg:
            continue

        gate = anchor_gate(item_agg.get("direction"), anchor,
                           strong_th=ANCHOR_STRONG_TH, weak_th=ANCHOR_WEAK_TH)
        if ANCHOR_ENFORCE and gate["action"] == "block":
            continue

        if best_quality >= float(min_quality):
            conf = int(item_agg.get("confidence") or 0)
            if gate["action"] == "downgrade":
                conf = max(0, conf - int(gate.get("penalty", 15)))
            elif gate["action"] == "boost":
                conf = min(100, conf + int(gate.get("bonus", 10)))

            reason = str(item_agg.get("reason") or "")
            reason = f"{reason}; anchor={anchor.get('direction')}/{anchor.get('strength')}"

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
                "confidence": conf,
                "reason": reason,
                "entry": item_agg.get("indicators", {}).get("close"),
                "atr": item_agg.get("indicators", {}).get("atr"),
            }))

    results.sort(key=lambda r: (r.quality_score or 0.0), reverse=True)
    results = results[:max(1, int(top))]
    return {"results": results}

# -------- Price --------
@app.get("/price", tags=["Trades"], summary="Get Price", response_model=PriceResponse, dependencies=[Depends(auth_dep)])
async def get_price(symbol: str):
    try:
        sym = normalize_symbol(symbol, market="futures", cache=symbols_cache)
        data = await _get_mark_price(sym)
        price = float(data.get("markPrice"))
        return {"symbol": sym, "price": price}
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))

# פרמטרים ל־SLTP
SLTP_MIN_PCT_FLOOR = float(os.getenv("SLTP_MIN_PCT_FLOOR", "0.0030"))   # 0.30%
SLTP_TP_PCT_FLOOR  = float(os.getenv("SLTP_TP_PCT_FLOOR",  "0.0060"))   # 0.60%
ATR_SL_MULT        = float(os.getenv("ATR_SL_MULT",        "1.50"))
ATR_TP_MULT        = float(os.getenv("ATR_TP_MULT",        "2.50"))

# -------- SLTP (עם כוונון לפי BTC) --------
@app.post("/sltp", tags=["Trades"], summary="Suggest SL/TP", response_model=SLTPResponse, dependencies=[Depends(auth_dep)])
async def suggest_sltp(req: SLTPRequest):
    try:
        sym = normalize_symbol(req.symbol, market="futures", cache=symbols_cache)
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))

    # ATR/רצפה
    atr = float(req.atr) if req.atr is not None else max(req.entry * SLTP_MIN_PCT_FLOOR, 1.0)
    base_sl = max(atr * ATR_SL_MULT, req.entry * SLTP_MIN_PCT_FLOOR)
    base_tp = max(atr * ATR_TP_MULT, req.entry * SLTP_TP_PCT_FLOOR)

    anchor = await compute_btc_anchor(frames=["15m", "1h"], market="futures")
    sl_mult, tp_mult = sltp_multipliers(req.direction, anchor,
                                        strong_th=ANCHOR_STRONG_TH, weak_th=ANCHOR_WEAK_TH)
    sl_dist = base_sl * sl_mult
    tp_dist = base_tp * tp_mult

    if req.direction == "LONG":
        sl = round(req.entry - sl_dist, 6)
        tp = round(req.entry + tp_dist, 6)
    else:
        sl = round(req.entry + sl_dist, 6)
        tp = round(req.entry - tp_dist, 6)

    return {"symbol": sym, "direction": req.direction, "sl": sl, "tp": tp}

# -------- AI analyze (ידני) --------
def _norm_direction_from_trend(trend: str) -> str:
    t = (trend or "").strip().lower()
    if t in ("up", "long", "buy", "bull", "bullish"):
        return "LONG"
    if t in ("down", "short", "sell", "bear", "bearish"):
        return "SHORT"
    return "SIDEWAYS"

@app.post("/ai-analyze", tags=["AI"], summary="Manual AI analysis", response_model=AiAnalyzeResponse, dependencies=[Depends(auth_dep)])
async def ai_analyze(req: AiAnalyzeRequest):
    frames = ["manual"]
    direction = _norm_direction_from_trend(req.trend)

    if analyze_with_ai:
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
        ai_res = await analyze_with_ai([tf_item])
        anchor = await compute_btc_anchor(frames=["15m", "1h"], market="futures")
        reason = (ai_res.get("reason") or "").strip()
        reason = (reason + f"; anchor={anchor.get('direction')}/{anchor.get('strength')}").strip("; ")
        return AiAnalyzeResponse(
            symbol=req.symbol.upper(),
            direction=direction,
            signal=ai_res.get("signal", "HOLD"),
            confidence=int(ai_res.get("confidence", 0)),
            reason=reason,
            frames=frames,
            metrics={"rsi": req.rsi, "adx": req.adx, "volume": req.volume, "pattern": req.pattern},
        )

    # פולבק דטרמיניסטי
    signal = "HOLD"
    conf = 50
    if direction == "LONG" and req.adx >= 22 and req.rsi >= 55:
        signal, conf = "BUY", 70
    elif direction == "SHORT" and req.adx >= 22 and req.rsi <= 45:
        signal, conf = "SELL", 70

    anchor = await compute_btc_anchor(frames=["15m", "1h"], market="futures")
    gate = anchor_gate(direction, anchor, strong_th=ANCHOR_STRONG_TH, weak_th=ANCHOR_WEAK_TH)
    if gate["action"] == "downgrade":
        conf = max(0, conf - int(gate.get("penalty", 15)))
    elif gate["action"] == "boost":
        conf = min(100, conf + int(gate.get("bonus", 10)))

    reason = f"trend={req.trend} rsi={req.rsi} adx={req.adx}; anchor={anchor.get('direction')}/{anchor.get('strength')}"
    return AiAnalyzeResponse(
        symbol=req.symbol.upper(),
        direction=direction,
        signal=signal,
        confidence=int(conf),
        reason=reason,
        frames=frames,
        metrics={"rsi": req.rsi, "adx": req.adx, "volume": req.volume, "pattern": req.pattern},
    )

# -------- Trade (עם Gate קשיח) --------
@app.post("/trade", tags=["Trades"], summary="Place Trade", response_model=TradeResponse, dependencies=[Depends(auth_dep)])
async def place_trade(req: TradeRequest):
    try:
        req.symbol = normalize_symbol(req.symbol, market="futures", cache=symbols_cache)
    except Exception as e:
        return JSONResponse(status_code=422, content={"status": "error", "error": str(e), "result": None})

    anchor = await compute_btc_anchor(frames=["15m", "1h"], market="futures")
    gate = anchor_gate(req.side, anchor, strong_th=ANCHOR_STRONG_TH, weak_th=ANCHOR_WEAK_TH)
    if ANCHOR_ENFORCE and gate["action"] == "block":
        return JSONResponse(status_code=409, content={
            "status": "error",
            "error": f"blocked by BTC anchor: {gate['reason']}",
            "result": None
        })

    if _ext_dry_run_trade is None:
        return JSONResponse(status_code=501, content={"status": "error", "error": "trade core not installed", "result": None})

    try:
        result = await _ext_dry_run_trade(req.model_dump())
        return {"status": "success", "result": result}
    except Exception as e:
        logger.exception("trade failed")
        return JSONResponse(status_code=500, content={"status": "error", "error": str(e), "result": None})

# -------- Grid (DRY-RUN אם אין מודול ייעודי) --------
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

    levels = [round(1.0 - (i * (req.grid_pct / 100.0)), 6) for i in range(req.grid_count)]
    plan = {
        "symbol": sym, "grid_count": req.grid_count, "grid_pct": req.grid_pct,
        "levels_mult": levels, "leverage": req.leverage, "futures": req.futures,
        "tp_pct": req.tp_pct, "sl_pct": req.sl_pct, "budget": req.budget,
    }

    if binance_grid_trade is None:
        return {"status": "dry_run", "plan": plan, "reason": "no dedicated grid executor"}

    try:
        result = await binance_grid_trade(plan)
        return {"status": "success", "plan": plan, "result": result}
    except Exception as e:
        logger.exception("grid trade failed")
        return {"status": "error", "error": str(e), "plan": plan}

# -------- Executor (in-mem demo) --------
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

# --- אליאסים תואמי-עבר ---
@app.get("/auto-executor/start", tags=["Executor"], dependencies=[Depends(auth_dep)])
async def auto_executor_start():
    return await start_executor()

@app.get("/auto-executor/stop", tags=["Executor"], dependencies=[Depends(auth_dep)])
async def auto_executor_stop():
    return await stop_executor()

@app.get("/auto-executor/status", tags=["Executor"], dependencies=[Depends(auth_dep)])
async def auto_executor_status():
    return await executor_status()

# -------- Reports --------
@app.get("/report/pnl/pdf", tags=["Reports"], summary="Generate PnL PDF", response_model=PnlPdfResponse, dependencies=[Depends(auth_dep)])
async def generate_pnl_pdf_route():
    """
    יוצר PDF מ- p p pnl_tracker.json ומחזיר נתיב נגיש תחת /static.
    """
    try:
        from utils.pnl_tracker import generate_pnl_pdf
        path = generate_pnl_pdf()
        if not path:
            raise HTTPException(status_code=404, detail="no PnL data")
        # ודא שהנתיב יחסי ונגיש:
        rel = path.replace("\\", "/")
        if not rel.startswith("/"):
            rel = "/" + rel
        return {"path": rel}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("pnl pdf failed")
        raise HTTPException(status_code=500, detail=str(e))

# -------- Debug Futures --------
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
        out["permission_ok"] = None
    return out

























































































































