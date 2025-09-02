# utils/auto\_executor.py

```python
from __future__ import annotations
import asyncio
import logging
import os
import time
from collections import deque
from typing import Optional, Dict, Any

import pandas as pd

from utils import config as cfg
from utils.indicators import prepare_indicators_for_backtest
from utils.binance_client import get_klines_df
from utils.anchor import evaluate_anchor
from utils.trade_executor import execute_trade_live
from utils.ws_fallback import get_price as ws_get_price

logger = logging.getLogger("algogpt.autoexec")

EXECUTOR_RUNNING = False
EXECUTOR_LAST_TS: Optional[float] = None
EXECUTOR_LOGS: deque[dict] = deque(maxlen=300)

INTERVAL = os.getenv("DEFAULT_INTERVAL", getattr(cfg, "DEFAULT_INTERVAL", "15m"))
SCAN_INTERVAL = getattr(cfg, "SCAN_INTERVAL", 60)
MAX_TRADES_PER_TICK = int(os.getenv("MAX_TRADES_PER_TICK", "1"))
SYMBOL_COOLDOWN_SEC = int(os.getenv("SYMBOL_COOLDOWN_SEC", "600"))

# סף איכות – נלקח מה-ENV דרך cfg; מומלץ להגדיר ל-8.5
QUALITY_THRESHOLD = max(0.0, float(os.getenv("MIN_QUALITY_SCORE", str(getattr(cfg, "MIN_QUALITY_SCORE", 8.5)))))

_last_trade_ts: Dict[str, float] = {}


def _log(event: str, level: str = "INFO", **kw):
    rec = {"event": event, **kw, "ts": time.time(), "level": level}
    EXECUTOR_LOGS.append(rec)
    getattr(logger, level.lower(), logger.info)(rec)


def _decide_side(row: Dict[str, Any]) -> Optional[str]:
    e21, e50 = row.get("ema_21"), row.get("ema_50")
    if e21 is None or e50 is None:
        return None
    if e21 > e50:
        return "LONG"
    if e21 < e50:
        return "SHORT"
    return None


def _quality_score(row: Dict[str, Any], side: str) -> float:
    """ציון 0–10 שמרני: טרנד + מומנטום + תנודתיות בריאה."""
    score = 0.0
    # טרנד
    if side == "LONG" and row.get("ema_21", 0) > row.get("ema_50", 0):
        score += 3.0
    if side == "SHORT" and row.get("ema_21", 0) < row.get("ema_50", 0):
        score += 3.0
    # מומנטום (MACD hist)
    hist = float(row.get("macd_hist") or 0.0)
    if (side == "LONG" and hist > 0) or (side == "SHORT" and hist < 0):
        score += 2.0
    # ADX (עוצמת מגמה)
    adx_v = float(row.get("adx") or 0.0)
    if adx_v >= 25:
        score += 2.5
    elif adx_v >= 20:
        score += 1.5
    # RSI: הימנעות מקיצון
    rsi_v = float(row.get("rsi") or 50.0)
    if 42 <= rsi_v <= 68:
        score += 1.0
    # נרשם ציון סופי [0,10]
    return max(0.0, min(10.0, score))


def _pick_leverage(adx_v: float) -> int:
    # מינוף דינמי שמרני לפי חוזק מגמה (ADX)
    base = 7
    if adx_v >= 30:
        base = 15
    elif adx_v >= 25:
        base = 12
    elif adx_v >= 20:
        base = 9
    return int(max(getattr(cfg, "MIN_LEVERAGE", 5), min(base, getattr(cfg, "MAX_LEVERAGE", 35))))


def _derive_sl_tp(entry: float, atr_v: float, side: str, adx_v: float) -> tuple[float, float]:
    # SL לפי ATR×multiplier; TP דינמי: חזק → רחב יותר
    sl_mult = float(getattr(cfg, "STOP_LOSS_ATR_MULTIPLIER", 1.5))
    tp_mult = 3.5 if adx_v >= 25 else 2.5
    if side == "LONG":
        sl = entry - sl_mult * atr_v
        tp = entry + tp_mult * atr_v
    else:
        sl = entry + sl_mult * atr_v
        tp = entry - tp_mult * atr_v
    return float(sl), float(tp)


async def _scan_symbol(symbol: str) -> Optional[Dict[str, Any]]:
    try:
        # Cooldown פר-סימבול
        last = _last_trade_ts.get(symbol, 0.0)
        if (time.time() - last) < SYMBOL_COOLDOWN_SEC:
            _log("cooldown_skip", symbol=symbol)
            return None

        # נרות וּאינדים
        df: pd.DataFrame = get_klines_df(symbol, interval=INTERVAL, limit=200)
        if df is None or df.empty:
            _log("no_klines", symbol=symbol, level="WARNING")
            return None
        ind = prepare_indicators_for_backtest(df)
        if ind.empty:
            _log("indicators_empty", symbol=symbol, level="WARNING")
            return None
        row = ind.iloc[-1].to_dict()

        side = _decide_side(row)
        if not side:
            _log("no_side", symbol=symbol)
            return None

        # Anchor (BTC sentiment) – מחסום מאקרו
        anchor = evaluate_anchor(side)
        if not getattr(anchor, "allow", True):
            _log("anchor_block", symbol=symbol, anchor=anchor.__dict__)
            return None

        # איכות
        q = _quality_score(row, side)
        if q < QUALITY_THRESHOLD:
            _log("quality_below_threshold", symbol=symbol, score=q, thr=QUALITY_THRESHOLD)
            return None

        entry = float(row.get("close") or df["close"].iloc[-1])
        atr_v = float(row.get("atr") or 0.0)
        adx_v = float(row.get("adx") or 0.0)
        if entry <= 0 or atr_v <= 0:
            _log("bad_entry_atr", symbol=symbol, entry=entry, atr=atr_v, level="WARNING")
            return None

        sl, tp = _derive_sl_tp(entry, atr_v, side, adx_v)
        lev = _pick_leverage(adx_v)

        return {
            "symbol": symbol,
            "side": side,
            "entry": entry,
            "sl": sl,
            "tp": tp,
            "leverage": lev,
            "score": q,
            "adx": adx_v,
            "atr": atr_v,
        }
    except Exception as e:
        _log("scan_error", symbol=symbol, error=str(e), level="ERROR")
        return None


async def _execute_plan(plan: Dict[str, Any]) -> Dict[str, Any]:
    dry = not getattr(cfg, "EXECUTE_TRADES", False)
    resp = await execute_trade_live(
        symbol=plan["symbol"],
        side=plan["side"],
        budget=float(getattr(cfg, "MAX_TRADE_BUDGET", 100.0)),
        leverage=int(plan["leverage"]),
        entry=float(plan["entry"]),
        sl=float(plan["sl"]),
        tp=float(plan["tp"]),
        dry_run=dry,
    )
    ok = bool(resp.get("ok"))
    if ok:
        _last_trade_ts[plan["symbol"]] = time.time()
    return resp


# ──────────────────────────────────────────────────────────────────────────────
# לולאת האקסקיוטר
# ──────────────────────────────────────────────────────────────────────────────
async def auto_scan_and_trade():
    global EXECUTOR_RUNNING, EXECUTOR_LAST_TS
    EXECUTOR_RUNNING = True
    try:
        watchlist = [s.upper() for s in getattr(cfg, "WATCHLIST", ["BTCUSDT","ETHUSDT"]) if isinstance(s, str)]
        if "BTCUSDT" not in watchlist:
            watchlist.insert(0, "BTCUSDT")

        while EXECUTOR_RUNNING:
            EXECUTOR_LAST_TS = time.time()
            _log("tick_start", list=watchlist)

            # לסריקה, נעצור במס' טריידים מקסימלי בטיק
            sent = 0
            for sym in watchlist:
                if sent >= MAX_TRADES_PER_TICK:
                    break
                plan = await _scan_symbol(sym)
                if not plan:
                    continue
                resp = await _execute_plan(plan)
                _log("trade_attempt", symbol=sym, plan=plan, resp_ok=bool(resp.get("ok")))
                if resp.get("ok"):
                    sent += 1

            # קריאת ניהול חי (אם מופעלת בקונפיג)
            try:
                from utils.open_trade_manager import manage_open_trades
                if getattr(cfg, "ALLOW_MANAGE_OPEN_TRADES", True):
                    await manage_open_trades(loop=False)
            except Exception as e:
                _log("manage_call_error", error=str(e), level="WARNING")

            await asyncio.sleep(SCAN_INTERVAL)
    finally:
        EXECUTOR_RUNNING = False
        EXECUTOR_LAST_TS = None
        _log("executor_stopped")


# ──────────────────────────────────────────────────────────────────────────────
# API להפעלה/עצירה מבחוץ
# ──────────────────────────────────────────────────────────────────────────────
def is_executor_running() -> bool:
    return EXECUTOR_RUNNING


def start_executor():
    global EXECUTOR_RUNNING
    if EXECUTOR_RUNNING:
        _log("executor_already_running")
        return
    _log("executor_starting")
    loop = asyncio.get_event_loop()
    if loop.is_running():
        loop.create_task(auto_scan_and_trade())
    else:
        loop.run_until_complete(auto_scan_and_trade())


def stop_executor():
    global EXECUTOR_RUNNING
    if EXECUTOR_RUNNING:
        EXECUTOR_RUNNING = False
        _log("executor_stopping")
    else:
        _log("executor_not_running")
```

---

# main.py (מעודכן להוספת ניהול חי של טריידים)

```python
# main.py
from __future__ import annotations

import os
import asyncio
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Tuple, Optional, Dict, Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse

IS_CLOUD = bool(os.getenv("RENDER") or os.getenv("RENDER_SERVICE_ID") or os.getenv("DYNO") or os.getenv("K_SERVICE"))
if not IS_CLOUD:
    try:
        from dotenv import load_dotenv  # type: ignore
        load_dotenv(override=False)
    except Exception:
        pass

def _to_bool(v: str | None, default: bool = False) -> bool:
    if v is None:
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "on")

def _parse_csv(s: str | None) -> List[str]:
    s = s or ""
    return [x.strip() for x in s.split(",") if x.strip()]

def _clean_key(s: str | None) -> str:
    return (s or "").strip().strip('"').replace("\r", "").replace("\n", "").replace("\t", "")

APP_VERSION = os.getenv("ALGOGPT_VERSION", "2.16.0")

from utils import config as cfg  # noqa: F401
from utils.config import dump_config_sanitized, LOG_LEVEL
from utils.response_limits import ResponseSizeLimiter
from utils.json_logger import setup_json_logging

from utils.binance_client import (
    fapi_ping, futures_balance,
    start_user_stream_keepalive, stop_user_stream,
)
from utils.ws_fallback import auto_price_updater, is_price_fresh, get_price

from utils.auth import extract_token, allow_all, token_matches

# ⬇️ חדש: ייבוא מנהל הטריידים החי והאקסקיוטר
from utils.open_trade_manager import manage_open_trades
from utils.auto_executor import start_executor, stop_executor, is_executor_running

logger = setup_json_logging()
logging.getLogger().setLevel(LOG_LEVEL)

def _ensure_dir(path: str) -> bool:
    p = Path(path)
    try:
        p.mkdir(parents=True, exist_ok=True)
        return True
    except PermissionError:
        logger.warning({"event": "mkdir_permission_denied", "dir": path})
        return False
    except Exception as e:
        logger.warning({"event": "mkdir_failed", "dir": path, "error": str(e)})
        return False

static_ok = _ensure_dir("static")
_ = _ensure_dir("logs")

app = FastAPI(title="AlgoGPT API", version=APP_VERSION, description="AlgoGPT — מסחר אלגוריתמי בזמן אמת")

app.add_middleware(ResponseSizeLimiter, max_bytes=int(os.getenv("RESPONSE_MAX_BYTES", "5242880")))
app.add_middleware(GZipMiddleware, minimum_size=1000)

CORS_ALLOWED = (os.getenv("CORS_ALLOW_ORIGINS", "*") or "*").strip()
CORS_ALLOW_CREDENTIALS = _to_bool(os.getenv("CORS_ALLOW_CREDENTIALS", "0"), False)
if CORS_ALLOWED == "*" and CORS_ALLOW_CREDENTIALS:
    CORS_ALLOW_CREDENTIALS = False
allow_origins = ["*"] if CORS_ALLOWED == "*" else _parse_csv(CORS_ALLOWED)
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=CORS_ALLOW_CREDENTIALS,
)

try:
    if static_ok and os.access("static", os.R_OK):
        app.mount("/static", StaticFiles(directory="static"), name="static")
    else:
        logger.warning({"event": "static_mount_skipped", "reason": "no_access_or_not_ok"})
except Exception as e:
    logger.warning({"event": "static_mount_failed", "error": str(e)})

# ---------- Auth middleware ----------
@app.middleware("http")
async def validate_token(request: Request, call_next):
    PUBLIC_PATHS = {
        "/", "/openapi.json",
        "/health", "/health/live", "/health_full",
        "/docs", "/redoc",
        "/telegram/webhook",  # webhook ציבורי; מאומת בכותרת
    }
    PUBLIC_PREFIXES = ["/price", "/static/"]

    path = request.url.path
    if request.method.upper() == "OPTIONS":
        return await call_next(request)
    if path in PUBLIC_PATHS or any(path.startswith(p) for p in PUBLIC_PREFIXES):
        return await call_next(request)
    if allow_all():
        return await call_next(request)

    auth_header = request.headers.get("Authorization", "")
    token = extract_token(
        request,
        authorization=auth_header,
        x_api_key=request.headers.get("X-API-Key"),
    )
    if not token_matches(token):
        return JSONResponse(status_code=401, content={"detail": "Invalid API key"})
    return await call_next(request)

# ---------- Routers ----------
def _include_router(module_path: str, attr: str = "router") -> None:
    try:
        mod = __import__(module_path, fromlist=[attr])
        router = getattr(mod, attr)
        app.include_router(router)
        logger.info({"event": "router_registered", "router": module_path, "attr": attr})
    except Exception as e:
        logger.warning({"event": "router_register_failed", "router": module_path, "attr": attr, "error": str(e)})

CORE_ROUTERS: List[Tuple[str, str]] = [
    ("routes.trade", "router"),
    ("routes.market", "router"),
    ("routes.binance_status", "router"),
    ("routes.executor", "router"),
    ("routes.orders", "router"),
    ("routes.price", "router"),
    ("routes.rpc", "router"),
]
if _to_bool(os.getenv("ENABLE_AI_ROUTES", "1"), True):
    CORE_ROUTERS.append(("routes.ai", "router"))

EXTRA_ROUTERS: List[Tuple[str, str]] = [
    ("routes.market_extra", "router"),
    ("routes.executor_extra", "router"),
    ("routes.anchor_extra", "router"),
    ("routes.ws_stream", "router"),
    ("routes.grid", "router"),
    ("routes.debug", "router"),
    ("routes.indicators", "router"),
    ("routes.telegram_bot", "router"),         # מאובטח: /telegram/set-webhook
    ("routes.telegram_bot", "router_public"),  # ציבורי:  /telegram/webhook
    ("routes.orderbook", "router"),            # עומק/לחץ ספר פקודות
    ("routes.metrics_extra", "router"),        # Long/Short Ratio, Delta Volume, Funding Heatmap
    ("routes.indicators_extra", "router"),     # VWAP / OBV / CVD
    ("routes.precision", "router"),            # Quantize
    ("routes.alerts", "router"),               # התראות
]
for mod, attr in CORE_ROUTERS:
    _include_router(mod, attr)
for mod, attr in EXTRA_ROUTERS:
    _include_router(mod, attr)

# ---------- Root & Health ----------
@app.get("/", tags=["Config"]) 
async def root_status():
    return {"ok": True, "status": "ok", "version": APP_VERSION}

@app.get("/health", tags=["Health"]) 
async def health():
    return {"ok": True, "status": "ok", "version": APP_VERSION}

@app.get("/health/live", tags=["Health"]) 
async def health_live():
    return {"ok": True, "status": "live"}

@app.get("/health_full", tags=["Health"]) 
async def health_full():
    from utils.ws_fallback import is_price_fresh, get_price
    from utils.binance_client import fapi_ping, futures_balance, start_user_stream_keepalive

    k = _clean_key(os.getenv("BINANCE_API_KEY")); s = _clean_key(os.getenv("BINANCE_API_SECRET"))
    key_len = len(k); sec_len = len(s)

    try:
        ping_ok = bool(fapi_ping())
    except Exception as e:
        ping_ok = False
        logger.warning({"event": "health_ping_error", "error": str(e)})

    try:
        bal = futures_balance()
        account_ok = isinstance(bal, list)
    except Exception as e:
        account_ok = False
        logger.warning({"event": "health_account_error", "error": str(e)})

    try:
        lk = start_user_stream_keepalive(period_sec=int(os.getenv("LISTENKEY_KEEPALIVE_SEC", "1800")))
        listen_key_ok = bool(lk)
    except Exception as e:
        listen_key_ok = False
        logger.warning({"event": "health_listenkey_error", "error": str(e)})

    symbols = _parse_csv(os.getenv("HEALTH_SYMBOLS", "BTCUSDT,ETHUSDT"))
    prices: Dict[str, Any] = {}
    for sym in symbols:
        prices[sym] = {
            "fresh": is_price_fresh(sym, max_age_sec=int(os.getenv("HEALTH_PRICE_MAX_AGE", "30"))),
            "price": get_price(sym),
        }

    return {
        "ok": bool((key_len == 64) and (sec_len == 64) and account_ok),
        "version": APP_VERSION,
        "binance": {
            "key_len": key_len,
            "secret_len": sec_len,
            "fapi_time_ok": ping_ok,
            "account_ok": account_ok,
            "listenKey_ok": listen_key_ok,
        },
        "prices": prices,
        "time": datetime.now(timezone.utc).isoformat(),
    }

@app.exception_handler(Exception)
async def handle_exception(request: Request, exc: Exception):
    logger.error({
        "event": "exception",
        "error": str(exc),
        "type": exc.__class__.__name__,
        "path": request.url.path,
        "time": datetime.now(timezone.utc).isoformat(),
    })
    return JSONResponse({"detail": str(exc)}, status_code=500)

_price_task: Optional[asyncio.Task] = None
_manager_task: Optional[asyncio.Task] = None  # ⬅️ חדש

@app.on_event("startup")
async def startup_event():
    global _price_task
    logger.info({
        "event": "startup",
        "APP_VERSION": APP_VERSION,
        "BINANCE_KEY_LEN": len(_clean_key(os.getenv("BINANCE_API_KEY"))),
        "OPENAI_KEY_LEN": len((os.getenv("OPENAI_API_KEY") or "").strip()),
        "config": dump_config_sanitized(),
    })
    try:
        start_user_stream_keepalive(period_sec=int(os.getenv("LISTENKEY_KEEPALIVE_SEC", "1800")))
        logger.info({"event": "listen_key_keepalive_started"})
    except Exception as e:
        logger.warning({"event": "listen_key_keepalive_failed", "error": str(e)})

    syms = [s.strip().upper() for s in os.getenv("SYMS", os.getenv("HEALTH_SYMBOLS","BTCUSDT,ETHUSDT,SOLUSDT")).split(",") if s.strip()]
    ws_keepalive = int(os.getenv("WS_KEEPALIVE_SEC", "25"))
    rest_every = int(os.getenv("PRICE_SCAN_INTERVAL", "15"))
    if syms:
        try:
            _price_task = asyncio.create_task(
                auto_price_updater(syms, ws_interval_keepalive=ws_keepalive, rest_interval_sec=rest_every)
            )
            logger.info({"event": "price_updater_started", "symbols": syms, "ws_keepalive": ws_keepalive, "rest_every": rest_every})
        except Exception as e:
            logger.warning({"event": "price_updater_failed_start", "error": str(e)})

@app.on_event("shutdown")
async def shutdown_event():
    global _price_task, _manager_task
    try:
        stop_user_stream()
        logger.info({"event": "listen_key_keepalive_stopped"})
    except Exception as e:
        logger.warning({"event": "listen_key_keepalive_stop_error", "error": str(e)})
    if _price_task:
        try:
            _price_task.cancel()
        except Exception:
            pass
        _price_task = None
    if _manager_task:
        try:
            _manager_task.cancel()
        except Exception:
            pass
        _manager_task = None

# ⬇️ אנדפוינטים חדשים לבקרת האוטומציה (ללא עומס כברירת מחדל)
@app.post("/start-executor", tags=["Executor"])
async def api_start_executor():
    try:
        start_executor()
        return {"ok": True, "msg": "executor started"}
    except Exception as e:
        logger.exception("start-executor failed")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

@app.post("/stop-executor", tags=["Executor"])
async def api_stop_executor():
    try:
        stop_executor()
        return {"ok": True, "msg": "executor stopping"}
    except Exception as e:
        logger.exception("stop-executor failed")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

@app.post("/manage-once", tags=["Manager"])
async def api_manage_once():
    try:
        await manage_open_trades(loop=False)
        return {"ok": True, "msg": "managed once"}
    except Exception as e:
        logger.exception("manage-once failed")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

@app.post("/start-manager", tags=["Manager"])
async def api_start_manager(interval: Optional[int] = None):
    global _manager_task
    if _manager_task and not _manager_task.done():
        return JSONResponse({"ok": False, "error": "manager already running"}, status_code=409)

    async def _bg():
        await manage_open_trades(loop=True, interval=interval)

    try:
        _manager_task = asyncio.create_task(_bg())
        return {"ok": True, "msg": "manager started", "interval": interval or getattr(cfg, "PRICE_MONITOR_INTERVAL", 30)}
    except Exception as e:
        logger.exception("start-manager failed")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

@app.post("/stop-manager", tags=["Manager"])
async def api_stop_manager():
    global _manager_task
    try:
        if _manager_task and not _manager_task.done():
            _manager_task.cancel()
            _manager_task = None
        return {"ok": True, "msg": "manager stopped"}
    except Exception as e:
        logger.exception("stop-manager failed")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

if __name__ == "__main__":
    import uvicorn
    bind_host = os.getenv("BIND_HOST", "0.0.0.0")
    bind_port = int(os.getenv("BIND_PORT", os.getenv("PORT", "8000")))
    uvicorn.run(
        "main:app",
        host=bind_host,
        port=bind_port,
        reload=_to_bool(os.getenv("UVICORN_RELOAD", "0")),
        log_level=os.getenv("UVICORN_LOG_LEVEL", "info"),
    )
```

















































































































































































































































































































































































































































































































