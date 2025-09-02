# utils/user_stream.py
from __future__ import annotations
import os, asyncio, json, time, logging, math
from typing import Dict, Any, Optional, Tuple, List

import httpx
import websockets

from utils import config as cfg
from utils.http_client import safe_get, get_client
from utils.binance_client import place_stop_market
from utils.precision_utils import apply_price_tick_side

logger = logging.getLogger("algogpt.userstream")

BINANCE_FAPI = cfg.BINANCE_FUTURES_HTTP_BASE
FWS_BASE = (os.getenv("BINANCE_FUTURES_WS_BASE") or "wss://fstream.binance.com").rstrip("/")
WS_KEEPALIVE_SEC = int(os.getenv("STREAM_WS_KEEPALIVE_SEC", os.getenv("WS_KEEPALIVE_SEC", "25")))
ORDER_EVENT_RATE_LIMIT = int(os.getenv("ORDER_EVENT_RATE_LIMIT", "15"))  # שניות קירור פר-סימבול
TP_BE_STAGE1 = float(os.getenv("TP_BE_STAGE1", "1"))       # אחרי TP1 → SL=BE
TP_LOCK_STAGE2_ATR = float(os.getenv("TP_LOCK_STAGE2_ATR", "0.5"))  # אחרי TP2 → מקבע רווח 0.5*ATR
STREAM_TP_BE = str(os.getenv("STREAM_TP_BE", "true")).lower() in ("1","true","yes","on")

# כדי להעריך ATR ולהבין איזה TP מולא
DEFAULT_INTERVAL = getattr(cfg, "DEFAULT_INTERVAL", "15m")
ATR_LIMIT = 200

# קירור פר-סימבול לעדכוני SL
_last_touch: Dict[str, float] = {}

# ======================================================================
# ListenKey lifecycle
# ======================================================================
async def _futures_listen_key() -> str:
    """
    מביא/מחדש listenKey. צריך כותרת X-MBX-APIKEY; לא דרוש חתימה.
    """
    headers = {
        "X-MBX-APIKEY": os.getenv("BINANCE_API_KEY","").strip(),
        "Accept": "application/json",
    }
    timeout = httpx.Timeout(8.0, connect=8.0)
    async with httpx.AsyncClient(timeout=timeout) as x:
        # נסה לקבל קיים (PUT keepalive יחזיר 200 גם אם קיים). אם לא – צור חדש.
        lk_env = os.getenv("BINANCE_LISTEN_KEY")
        if lk_env:
            try:
                r = await x.put(f"{BINANCE_FAPI}/fapi/v1/listenKey", headers=headers)
                if r.status_code == 200:
                    return lk_env.strip()
            except Exception:
                pass
        # צור חדש
        r = await x.post(f"{BINANCE_FAPI}/fapi/v1/listenKey", headers=headers)
        r.raise_for_status()
        lk = (r.json() or {}).get("listenKey")
        if not lk:
            raise RuntimeError("failed to obtain listenKey")
        return lk

async def _keepalive_loop(lk: str):
    headers = {
        "X-MBX-APIKEY": os.getenv("BINANCE_API_KEY","").strip(),
        "Accept": "application/json",
    }
    timeout = httpx.Timeout(8.0, connect=8.0)
    async with httpx.AsyncClient(timeout=timeout) as x:
        while True:
            try:
                await x.put(f"{BINANCE_FAPI}/fapi/v1/listenKey", headers=headers)
            except Exception as e:
                logger.warning({"event":"listenkey_keepalive_error","error":str(e)})
            await asyncio.sleep(int(os.getenv("LISTENKEY_KEEPALIVE_SEC","1800")))

# ======================================================================
# ATR / שליפת קליינים לצורך השוואת TP
# ======================================================================
async def _fetch_klines_df(symbol: str, interval: str, limit: int):
    r = await safe_get(f"{BINANCE_FAPI}/fapi/v1/klines", params={"symbol":symbol,"interval":interval,"limit":limit})
    arr = r.json()
    import pandas as pd
    cols = ["open_time","open","high","low","close","volume","close_time","qv","nTrades","taker_base","taker_quote","x"]
    df = pd.DataFrame(arr, columns=cols[:len(arr[0])])
    for c in ("open","high","low","close","volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df

def _atr(df) -> float:
    try:
        import pandas as pd, numpy as np
        high = df["high"].astype(float)
        low  = df["low"].astype(float)
        close= df["close"].astype(float)
        prev_close = close.shift(1).fillna(close.iloc[0])
        tr = pd.concat([(high-low),(high-prev_close).abs(),(low-prev_close).abs()], axis=1).max(axis=1)
        # Wilder RMA(14)
        alpha = 1/14.0
        r = [tr.iloc[0]]
        for i in range(1,len(tr)):
            r.append(r[-1]*(1-alpha) + alpha*tr.iloc[i])
        return float(r[-1])
    except Exception:
        return 0.0

def _tp_stage(side: str, entry: float, atr: float, price: float) -> int:
    """
    מחזיר 1/2/3 לפי המחיר הקרוב ביותר ל: entry ± [1.0,1.8,2.6] ATR.
    """
    sgn = 1.0 if side.upper() in ("BUY","LONG") else -1.0
    targets = [entry + sgn*1.0*atr, entry + sgn*1.8*atr, entry + sgn*2.6*atr]
    # הקרוב ביותר
    idx = min(range(3), key=lambda i: abs(targets[i]-price))
    return idx+1

# ======================================================================
# עדכון SL
# ======================================================================
async def _set_sl(symbol: str, side: str, price: float, qty: float) -> bool:
    # יישור לטיק והצבה כ-Reduce-Only
    close_side = "SELL" if side.upper() in ("BUY","LONG") else "BUY"
    px, _ = apply_price_tick_side(price, symbol, close_side)
    try:
        place_stop_market(symbol, close_side, float(px), float(qty), reduce_only=True)
        return True
    except Exception as e:
        logger.warning({"event":"set_sl_failed","symbol":symbol,"err":str(e)})
        return False

# ======================================================================
# לוגיקת TP→SL
# ======================================================================
async def _on_tp_filled(symbol: str, side: str, entry: float, filled_price: float, position_qty: float):
    """
    אחרי מילוי TP:
      - TP1: SL → BE (entry)
      - TP2: SL → entry ± TP_LOCK_STAGE2_ATR * ATR (לכיוון רווח)
      - TP3: לא משנים (כבר רוב הפוזיציה יצאה); אפשר להשאיר טריילינג ע"י open_trade_manager
    """
    if not STREAM_TP_BE:
        return

    # קירור עומס
    now = time.time()
    if (now - _last_touch.get(symbol, 0.0)) < ORDER_EVENT_RATE_LIMIT:
        return

    # שולף ATR כדי להבין באיזה TP מדובר והיכן למקם SL בשלב 2
    try:
        df = await _fetch_klines_df(symbol, DEFAULT_INTERVAL, ATR_LIMIT)
        atr_v = _atr(df)
    except Exception as e:
        logger.warning({"event":"tp_fill_atr_fetch_failed","symbol":symbol,"err":str(e)})
        atr_v = 0.0

    stage = _tp_stage(side, entry, atr_v or max(1e-8, abs(entry)*0.001), filled_price)

    # כמות לנעילה – נצמד ל-SL על כל יתרת הפוזיציה
    qty = max(0.0, float(position_qty or 0.0))
    if qty <= 0:
        return

    if stage == 1:
        # SL -> BE
        ok = await _set_sl(symbol, side, entry, qty)
        if ok:
            _last_touch[symbol] = now
            logger.info({"event":"tp1_be_sl_set","symbol":symbol,"entry":entry,"qty":qty})
    elif stage == 2:
        # נעילת רווח ATR*TP_LOCK_STAGE2_ATR
        sgn = 1.0 if side.upper() in ("BUY","LONG") else -1.0
        lock_px = entry + sgn * (TP_LOCK_STAGE2_ATR * (atr_v or 0.0))
        # לא ננעל פחות מ-BE
        if side.upper() in ("BUY","LONG"):
            lock_px = max(lock_px, entry)
        else:
            lock_px = min(lock_px, entry)
        ok = await _set_sl(symbol, side, lock_px, qty)
        if ok:
            _last_touch[symbol] = now
            logger.info({"event":"tp2_lock_sl_set","symbol":symbol,"lock_px":lock_px,"qty":qty})
    else:
        # TP3 – לא מזיזים; open_trade_manager יטרייל
        logger.info({"event":"tp3_no_change","symbol":symbol})

# ======================================================================
# Decode ORDER_TRADE_UPDATE
# ======================================================================
def _is_reduce_only_take_profit(o: Dict[str, Any]) -> bool:
    ty = str(o.get("o","")).upper()  # order type
    ro = str(o.get("R","")).lower()  # reduceOnly (as "true"/"false")
    return (ty.startswith("TAKE_PROFIT") and ro in ("true","1"))

def _status_filled(o: Dict[str, Any]) -> bool:
    st = str(o.get("X","")).upper()  # orderStatus
    return st in ("FILLED","PARTIALLY_FILLED","PARTIALLY_FILLED_PART")

def _extract_exec(o: Dict[str, Any]) -> Tuple[str,str,float,float,float]:
    """
    החזרה: (symbol, side, entry_guess, filled_price, last_position_qty)
    הערה: entry האמיתי לא מגיע באירוע הזמנה; נוערך אותו ע"י:
      - 'ap' (avgPrice) אם יש
      - ואם לא – נשלוף מה-position info ב-open_trade_manager בבדיקה עתידית,
        כאן מספיק לנו הערכה למיקום BE. לכן נשתמש ב-ap או ב-sp/price כגיבוי.
    """
    sym = str(o.get("s") or "").upper()
    side = str(o.get("S") or "").upper()
    filled_price = float(o.get("ap") or o.get("sp") or o.get("p") or 0.0)
    # position qty מגיע ב-p["rp"]? לא. לכן נצטרך למשוך בהמשך מ-position Risk.
    # כאן נחזיר 0 — ונבקש מהקריאה הקוראת לנו לספק qty נכון אם יש לה.
    entry_guess = float(o.get("ap") or 0.0)
    last_qty = 0.0
    return sym, side, entry_guess, filled_price, last_qty

# ======================================================================
# public: consumer
# ======================================================================
_running = False
_ws_task: Optional[asyncio.Task] = None
_keepalive_task: Optional[asyncio.Task] = None

async def _positions_lookup(symbol: str) -> Tuple[float,float]:
    """
    מביא (entry, positionQty) אמיתיים מהחשבון כדי שנוכל להצמיד SL ליתרה.
    """
    try:
        from utils.open_trade_manager import _fetch_positions  # reuse
        pos = _fetch_positions()
        for p in pos:
            if str(p.get("symbol","")).upper() == symbol.upper():
                return float(p.get("entry") or 0.0), float(p.get("qty") or 0.0)
    except Exception:
        pass
    return 0.0, 0.0

async def _consumer():
    global _running, _keepalive_task
    lk = await _futures_listen_key()
    _keepalive_task = asyncio.create_task(_keepalive_loop(lk))
    url = f"{FWS_BASE}/ws/{lk}"
    backoff = 1.5
    while _running:
        try:
            logger.info({"event":"user_ws_connecting","url":url})
            async with websockets.connect(
                url, ping_interval=WS_KEEPALIVE_SEC, ping_timeout=10, close_timeout=5, max_size=1_000_000
            ) as ws:
                backoff = 1.5
                while _running:
                    raw = await ws.recv()
                    data = json.loads(raw)
                    if str(data.get("e") or "").upper() == "ORDER_TRADE_UPDATE":
                        o = data.get("o") or {}
                        if _is_reduce_only_take_profit(o) and _status_filled(o):
                            sym, side, entry_guess, fp, _ = _extract_exec(o)
                            # נביא entry/qty אמתיים
                            entry, qty = await _positions_lookup(sym)
                            if entry <= 0:
                                entry = entry_guess or fp
                            if qty > 0 and entry > 0:
                                try:
                                    await _on_tp_filled(sym, side, entry, fp, qty)
                                except Exception as e:
                                    logger.warning({"event":"tp_on_filled_error","symbol":sym,"err":str(e)})
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning({"event":"user_ws_error","error":str(e)})
            await asyncio.sleep(min(60, backoff))
            backoff = min(backoff*1.7, 60.0)

async def start_user_stream_consumer():
    """
    מפעיל צרכן user-data stream ברקע (חסין עומסים; backoff; קירור).
    """
    global _running, _ws_task
    if _running:
        return
    _running = True
    loop = asyncio.get_event_loop()
    _ws_task = loop.create_task(_consumer())
    logger.info({"event":"user_stream_started"})

async def stop_user_stream_consumer():
    global _running, _ws_task, _keepalive_task
    _running = False
    try:
        if _ws_task and not _ws_task.done():
            _ws_task.cancel()
    except Exception:
        pass
    _ws_task = None
    try:
        if _keepalive_task and not _keepalive_task.done():
            _keepalive_task.cancel()
    except Exception:
        pass
    _keepalive_task = None
    logger.info({"event":"user_stream_stopped"})
