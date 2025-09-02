# utils/open\_trade\_manager.py

```python
from __future__ import annotations
import asyncio
import time
import logging
from typing import Dict, Optional

import pandas as pd

from utils import config as cfg
from utils.indicators import atr, adx, macd
from utils.binance_client import (
    get_open_positions,           # → List[dict] of futures positions
    get_klines_df,                # → pd.DataFrame with columns: open, high, low, close, volume
    futures_mark_price,           # → float
    modify_stop_loss,             # (symbol, close_side, price, qty, reduce_only=True)
    modify_take_profit,           # (symbol, close_side, price, qty, reduce_only=True)
)
from utils.ws_fallback import get_price as ws_get_price
from utils.redis_client import redis_client

logger = logging.getLogger("algogpt.open_trade_manager")

# ──────────────────────────────────────────────────────────────────────────────
# Runtime knobs (safe defaults; can be overridden via ENV in cfg if desired)
# ──────────────────────────────────────────────────────────────────────────────
MANAGE_DEFAULT_INTERVAL_SEC = 60             # ניהול כל 60 שניות
PER_SYMBOL_COOLDOWN_SEC      = 30            # כל סימבול לא יותר מפעם ב‑30 שניות
MIN_BE_PROFIT_PCT            = 1.5           # Breakeven רק מעל רווח זה
ADX_MIN_FOR_BE               = 20            # או MACD>0
ADX_FOR_TP_EXPAND            = 25            # להגדלת TP
TRAIL_ATR_MULT               = 0.6           # SL = swing ± 0.6×ATR
TRAIL_GUARD_ATR              = 0.2           # לא להצמיד SL קרוב מ‑0.2×ATR למחיר
TP_MOMENTUM_ATR_MULT         = 4.5           # הגדלת TP = מחיר ± 4.5×ATR

# אחסון מצב מינימלי ב‑Redis כדי להבטיח "הידוק בלבד"
REDIS_SL_KEY = "algogpt:manage:last_sl:{}"   # symbol → last sl we set
REDIS_TP_KEY = "algogpt:manage:last_tp:{}"   # symbol → last tp we set

_last_check_ts: Dict[str, float] = {}


def _close_side(side: str) -> str:
    su = (side or "").upper()
    return "SELL" if su in ("LONG", "BUY") else "BUY"


def _profit_pct(side: str, entry: float, price: float) -> float:
    if entry <= 0 or price <= 0:
        return 0.0
    if (side or "").upper() in ("LONG", "BUY"):
        return (price - entry) / entry * 100.0
    return (entry - price) / entry * 100.0


def _redis_get_float(key: str) -> Optional[float]:
    try:
        raw = redis_client.get(key) if redis_client else None
        return float(raw) if raw is not None else None
    except Exception:
        return None


def _redis_set_float(key: str, val: float, ttl: int = 7 * 24 * 3600) -> None:
    try:
        if not redis_client:
            return
        redis_client.setex(key, ttl, str(float(val)))
    except Exception:
        pass


async def _manage_symbol(sym: str, side: str, entry: float, qty: float) -> None:
    """ניהול סמבול בודד: BE / Trailing SL / TP Expand. שמרני, ללא עומס.
    Preconditions: qty != 0, entry > 0.
    """
    now = time.time()
    last = _last_check_ts.get(sym, 0.0)
    if (now - last) < PER_SYMBOL_COOLDOWN_SEC:
        return

    # מקור מחיר: WS (מהיר) → fallback Binance mark price
    price = ws_get_price(sym) or futures_mark_price(sym)
    if not price or price <= 0:
        return

    # נתוני נרות ל‑5m
    df: pd.DataFrame = get_klines_df(sym, interval="5m", limit=120)
    if df is None or df.empty or df.shape[0] < 30:
        return

    # אינדיקטורים
    atr_series = atr(df, 14)
    adx_series = adx(df, 14)
    macd_line, macd_signal, macd_hist = macd(df["close"])  # macd_line - signal = hist

    current_atr = float(atr_series.iloc[-1]) if not atr_series.empty else 0.0
    current_adx = float(adx_series.iloc[-1]) if not adx_series.empty else 0.0
    macd_now = float(macd_line.iloc[-1] - macd_signal.iloc[-1]) if not macd_line.empty else 0.0

    if current_atr <= 0:
        return

    profit = _profit_pct(side, entry, price)
    close_side = _close_side(side)

    # שליפה/שמירה של ערכי SL/TP שנשלחו בעבר כדי להבטיח הידוק בלבד
    last_sl_key = REDIS_SL_KEY.format(sym)
    last_tp_key = REDIS_TP_KEY.format(sym)
    last_sl = _redis_get_float(last_sl_key)
    last_tp = _redis_get_float(last_tp_key)

    # ── 1) Breakeven SL ───────────────────────────────────────────────────────
    be_candidate: Optional[float] = None
    if profit >= MIN_BE_PROFIT_PCT and (macd_now > 0.0 or current_adx >= ADX_MIN_FOR_BE):
        be_candidate = entry  # שמרני: בדיוק מחיר כניסה

    # ── 2) Trailing SL (swing ± 0.6×ATR) ─────────────────────────────────────
    trail_candidate: Optional[float] = None
    if (side or "").upper() in ("LONG", "BUY"):
        recent_low = float(df["low"].iloc[-3: ].min())
        trail_candidate = max(be_candidate or -1e18, recent_low - TRAIL_ATR_MULT * current_atr)
        # Guard: לא להצמיד קרוב מדי למחיר
        trail_candidate = min(trail_candidate, price - TRAIL_GUARD_ATR * current_atr)
        # Guard: לא להדק אחורה
        if last_sl is not None:
            trail_candidate = max(trail_candidate, last_sl)
    else:  # SHORT
        recent_high = float(df["high"].iloc[-3: ].max())
        trail_candidate = min(be_candidate or 1e18, recent_high + TRAIL_ATR_MULT * current_atr)
        trail_candidate = max(trail_candidate, price + TRAIL_GUARD_ATR * current_atr)
        if last_sl is not None:
            trail_candidate = min(trail_candidate, last_sl)

    # קביעת SL יעד סופי
    new_sl: Optional[float] = None
    if be_candidate is not None:
        new_sl = be_candidate
    if trail_candidate is not None:
        # ב‑LONG נרצה SL גבוה יותר; ב‑SHORT SL נמוך יותר
        if (side or "").upper() in ("LONG", "BUY"):
            new_sl = max(new_sl or -1e18, trail_candidate)
        else:
            new_sl = min(new_sl or 1e18, trail_candidate)

    # ── 3) Dynamic TP (momentum expansion) ───────────────────────────────────
    new_tp: Optional[float] = None
    if current_adx >= ADX_FOR_TP_EXPAND and macd_now > 0.0:
        if (side or "").upper() in ("LONG", "BUY"):
            new_tp = price + TP_MOMENTUM_ATR_MULT * current_atr
            # הגדלת TP רק מעלה
            if last_tp is not None:
                new_tp = max(new_tp, last_tp)
        else:
            new_tp = price - TP_MOMENTUM_ATR_MULT * current_atr
            if last_tp is not None:
                new_tp = min(new_tp, last_tp)

    # ── 4) שליחת עדכונים לבורסה (רק אם ALLOW_MANAGE_OPEN_TRADES=True) ──────
    if not cfg.ALLOW_MANAGE_OPEN_TRADES:
        logger.debug("[manage] skipped – ALLOW_MANAGE_OPEN_TRADES is False")
        _last_check_ts[sym] = now
        return

    updates = []
    try:
        abs_qty = abs(float(qty))
        if abs_qty <= 0:
            _last_check_ts[sym] = now
            return

        # Update SL (הידוק בלבד)
        if new_sl is not None:
            do_update_sl = False
            if (side or "").upper() in ("LONG", "BUY"):
                do_update_sl = (last_sl is None) or (new_sl > (last_sl + 1e-9))
                # אל תצמיד מעל המחיר
                if new_sl >= price:
                    do_update_sl = False
            else:
                do_update_sl = (last_sl is None) or (new_sl < (last_sl - 1e-9))
                if new_sl <= price:
                    do_update_sl = False

            if do_update_sl:
                try:
                    modify_stop_loss(sym, _close_side(side), float(new_sl), float(abs_qty), reduce_only=True)
                    _redis_set_float(last_sl_key, float(new_sl))
                    updates.append({"sl": new_sl})
                except Exception as e:
                    logger.error({"event": "sl_update_failed", "symbol": sym, "error": str(e)})

        # Update TP (הרחבה בלבד)
        if new_tp is not None:
            do_update_tp = False
            if (side or "").upper() in ("LONG", "BUY"):
                do_update_tp = (last_tp is None) or (new_tp > (last_tp + 1e-9))
            else:
                do_update_tp = (last_tp is None) or (new_tp < (last_tp - 1e-9))

            if do_update_tp:
                try:
                    modify_take_profit(sym, _close_side(side), float(new_tp), float(abs_qty), reduce_only=True)
                    _redis_set_float(last_tp_key, float(new_tp))
                    updates.append({"tp": new_tp})
                except Exception as e:
                    logger.error({"event": "tp_update_failed", "symbol": sym, "error": str(e)})

        if updates:
            logger.info({"event": "managed", "symbol": sym, "updates": updates, "price": price, "profit_pct": round(profit,2)})
    finally:
        _last_check_ts[sym] = now


async def manage_open_trades(*, loop: bool = False, interval: Optional[int] = None) -> None:
    """מנהל את כל הטריידים הפתוחים מול Binance API – ללא עומס, ביד‑הדוק.
    אם loop=True ירוץ ברקע בלולאה; אחרת – מעבר אחד.
    """
    if interval is None:
        interval = int(getattr(cfg, "PRICE_MONITOR_INTERVAL", MANAGE_DEFAULT_INTERVAL_SEC))
        if interval <= 0:
            interval = MANAGE_DEFAULT_INTERVAL_SEC

    async def _once():
        try:
            # משיכת פוזיציות פתוחות בלבד
            positions = get_open_positions() or []
            for p in positions:
                try:
                    sym = str(p.get("symbol") or "").upper()
                    qty = float(p.get("positionAmt") or 0.0)
                    if abs(qty) <= 0.0:
                        continue
                    entry = float(p.get("entryPrice") or 0.0)
                    side = "LONG" if qty > 0 else "SHORT"
                    await _manage_symbol(sym, side, entry, qty)
                except Exception as e:
                    logger.error({"event": "manage_symbol_error", "error": str(e), "pos": p})
        except Exception as e:
            logger.error({"event": "manage_once_error", "error": str(e)})

    if not loop:
        await _once()
        return

    logger.info({"event": "open_trade_manager_started", "interval_sec": interval})
    while True:
        await _once()
        await asyncio.sleep(max(5, int(interval)))
```

---

# main.py

```python
from __future__ import annotations
import os
import asyncio
import logging
from typing import Optional

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from utils import config as cfg
from utils.config import check_config
from utils.open_trade_manager import manage_open_trades
from utils.auto_executor import start_executor, stop_executor, is_executor_running  # אם אצלך שמות אחרים – עדכן כאן

logging.basicConfig(level=getattr(logging, cfg.LOG_LEVEL, "INFO"))
logger = logging.getLogger("algogpt.main")

app = FastAPI(title="AlgoGPT", version=os.getenv("ALGOGPT_VERSION", "2.x"))

_manager_task: Optional[asyncio.Task] = None


@app.on_event("startup")
async def _startup() -> None:
    # ולידציה של קונפיג – תעצור את האפליקציה אם משהו לא תקין
    try:
        check_config()
    except Exception as e:
        logger.error(f"[CONFIG] {e}")
        raise

    # לא מריצים אוטומטית כלום כאן – שליטה ע"י אנדפוינטים (למניעת עומס)
    logger.info("🚀 AlgoGPT API started. Use /start-executor or /start-manager to run loops.")


@app.get("/health")
async def health():
    return {"ok": True, "executor_running": is_executor_running()}


@app.post("/start-executor")
async def api_start_executor():
    try:
        start_executor()
        return {"ok": True, "msg": "executor started"}
    except Exception as e:
        logger.exception("start-executor failed")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.post("/stop-executor")
async def api_stop_executor():
    try:
        stop_executor()
        return {"ok": True, "msg": "executor stopping"}
    except Exception as e:
        logger.exception("stop-executor failed")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.post("/manage-once")
async def api_manage_once():
    try:
        await manage_open_trades(loop=False)
        return {"ok": True, "msg": "managed once"}
    except Exception as e:
        logger.exception("manage-once failed")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.post("/start-manager")
async def api_start_manager(interval: Optional[int] = None):
    global _manager_task
    if _manager_task and not _manager_task.done():
        return JSONResponse({"ok": False, "error": "manager already running"}, status_code=409)

    async def _bg():
        await manage_open_trades(loop=True, interval=interval)

    try:
        _manager_task = asyncio.create_task(_bg())
        return {"ok": True, "msg": "manager started", "interval": interval or cfg.PRICE_MONITOR_INTERVAL}
    except Exception as e:
        logger.exception("start-manager failed")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.post("/stop-manager")
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


# לוקאלי / דוקר
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "10000"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=os.getenv("UVICORN_RELOAD", "0") == "1")
```
