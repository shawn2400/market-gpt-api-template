# utils/user_stream.py
from __future__ import annotations
import os, asyncio, json, time, logging
from typing import Dict, Any, Optional, Tuple

import httpx, websockets

from utils import config as cfg
from utils.http_client import safe_get
from utils.binance_client import place_stop_market
from utils.precision_utils import apply_price_tick_side

logger = logging.getLogger("algogpt.userstream")

# ===== ENV =====
BINANCE_FAPI = cfg.BINANCE_FUTURES_HTTP_BASE
FWS_BASE = (os.getenv("BINANCE_FUTURES_WS_BASE") or "wss://fstream.binance.com").rstrip("/")
WS_KEEPALIVE_SEC = int(os.getenv("STREAM_WS_KEEPALIVE_SEC", os.getenv("WS_KEEPALIVE_SEC", "25")))
ORDER_EVENT_RATE_LIMIT = int(os.getenv("ORDER_EVENT_RATE_LIMIT", "15"))
STREAM_TP_BE = str(os.getenv("STREAM_TP_BE", "true")).lower() in ("1","true","yes","on")
TP_LOCK_STAGE2_ATR = float(os.getenv("TP_LOCK_STAGE2_ATR", "0.5"))

DEFAULT_INTERVAL = getattr(cfg, "DEFAULT_INTERVAL", "15m")
ATR_LIMIT = 200

_last_touch: Dict[str, float] = {}

# ===== ATR utils =====
async def _fetch_klines_df(symbol: str):
    try:
        r = await safe_get(
            f"{BINANCE_FAPI}/fapi/v1/klines",
            params={"symbol": symbol, "interval": DEFAULT_INTERVAL, "limit": ATR_LIMIT},
        )
        arr = r.json()
        import pandas as pd
        cols = [
            "open_time", "open", "high", "low", "close", "volume",
            "close_time", "qv", "nTrades", "taker_base", "taker_quote", "x",
        ]
        df = pd.DataFrame(arr, columns=cols[: len(arr[0])])
        for c in ("open", "high", "low", "close", "volume"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
        return df
    except Exception as e:
        logger.warning({"event": "klines_fetch_failed", "symbol": symbol, "err": str(e)})
        return None

def _atr(df) -> float:
    try:
        import pandas as pd
        high = df["high"].astype(float)
        low = df["low"].astype(float)
        close = df["close"].astype(float)
        prev_close = close.shift(1).fillna(close.iloc[0])
        tr = pd.concat(
            [(high - low), (high - prev_close).abs(), (low - prev_close).abs()],
            axis=1,
        ).max(axis=1)
        alpha = 1 / 14.0
        r = [tr.iloc[0]]
        for i in range(1, len(tr)):
            r.append(r[-1] * (1 - alpha) + alpha * tr.iloc[i])
        return float(r[-1])
    except Exception:
        return 0.0

# ===== Position lookup =====
async def _positions_lookup(symbol: str) -> Tuple[float, float, str]:
    try:
        from utils.open_trade_manager import _positions as _pos
        pos = _pos()
        for p in pos:
            if str(p.get("symbol", "")).upper() == symbol.upper():
                return (
                    float(p.get("entry") or 0.0),
                    float(p.get("qty") or 0.0),
                    str(p.get("side") or ""),
                )
    except Exception:
        pass
    return 0.0, 0.0, ""

# ===== Helpers =====
async def _set_sl(symbol: str, side: str, price: float, qty: float) -> bool:
    close_side = "SELL" if side.upper() in ("BUY", "LONG") else "BUY"
    px, _ = apply_price_tick_side(price, symbol, close_side)
    try:
        place_stop_market(symbol, close_side, float(px), float(qty), reduce_only=True)
        return True
    except Exception as e:
        logger.warning({"event": "set_sl_failed", "symbol": symbol, "err": str(e)})
        return False

def _stage_from_label(label: str) -> Optional[int]:
    L = label.upper()
    if "TP1" in L:
        return 1
    if "TP2" in L:
        return 2
    if "TP3" in L:
        return 3
    return None

# ===== TP handler =====
async def _on_tp(symbol: str, side: str, filled_price: float, label: Optional[str]):
    now = time.time()
    if (now - _last_touch.get(symbol, 0.0)) < ORDER_EVENT_RATE_LIMIT:
        return
    entry, qty, side_ok = await _positions_lookup(symbol)
    if not qty or not entry:
        return

    if not STREAM_TP_BE:
        return

    stage = _stage_from_label(label or "")
    if stage is None:
        # ATR-based fallback
        try:
            df = await _fetch_klines_df(symbol)
            atr_v = _atr(df) if df is not None else 0.0
        except Exception:
            atr_v = 0.0
        sgn = 1.0 if side.upper() in ("BUY", "LONG") else -1.0
        t1 = entry + sgn * 1.0 * atr_v
        t2 = entry + sgn * 1.8 * atr_v
        t3 = entry + sgn * 2.6 * atr_v
        targets = [t1, t2, t3]
        stage = min(range(3), key=lambda i: abs(targets[i] - filled_price)) + 1

    if stage == 1:
        ok = await _set_sl(symbol, side, entry, qty)
        if ok:
            _last_touch[symbol] = now
            logger.info({"event": "tp1_be_sl_set", "symbol": symbol})
    elif stage == 2:
        try:
            df = await _fetch_klines_df(symbol)
            atr_v = _atr(df) if df is not None else 0.0
        except Exception:
            atr_v = 0.0
        sgn = 1.0 if side.upper() in ("BUY", "LONG") else -1.0
        lock_px = entry + sgn * (TP_LOCK_STAGE2_ATR * atr_v)
        if side.upper() in ("BUY", "LONG"):
            lock_px = max(lock_px, entry)
        else:
            lock_px = min(lock_px, entry)
        ok = await _set_sl(symbol, side, lock_px, qty)
        if ok:
            _last_touch[symbol] = now
            logger.info({"event": "tp2_lock_sl_set", "symbol": symbol, "lock": lock_px})
    else:
        logger.info({"event": "tp3_no_change", "symbol": symbol})

# ===== WS logic =====
_running = False
_ws_task: Optional[asyncio.Task] = None
_keepalive_task: Optional[asyncio.Task] = None

async def _futures_listen_key() -> str:
    headers = {
        "X-MBX-APIKEY": os.getenv("BINANCE_API_KEY", "").strip(),
        "Accept": "application/json",
    }
    to = httpx.Timeout(8.0, connect=8.0)
    async with httpx.AsyncClient(timeout=to) as x:
        r = await x.post(f"{BINANCE_FAPI}/fapi/v1/listenKey", headers=headers)
        r.raise_for_status()
        lk = (r.json() or {}).get("listenKey")
        if not lk:
            raise RuntimeError("no listenKey")
        return lk

async def _keepalive_loop(lk: str):
    headers = {
        "X-MBX-APIKEY": os.getenv("BINANCE_API_KEY", "").strip(),
        "Accept": "application/json",
    }
    to = httpx.Timeout(8.0, connect=8.0)
    async with httpx.AsyncClient(timeout=to) as x:
        while True:
            try:
                await x.put(f"{BINANCE_FAPI}/fapi/v1/listenKey", headers=headers)
            except Exception as e:
                logger.warning({"event": "listenkey_keepalive_error", "error": str(e)})
            await asyncio.sleep(int(os.getenv("LISTENKEY_KEEPALIVE_SEC", "1800")))

def _is_reduce_only_tp(o: Dict[str, Any]) -> bool:
    ty = str(o.get("o", "")).upper()
    ro = str(o.get("R", "")).lower() in ("true", "1")
    st = str(o.get("X", "")).upper()
    return ty.startswith("TAKE_PROFIT") and ro and st in ("FILLED", "PARTIALLY_FILLED")

async def _consumer():
    lk = await _futures_listen_key()
    global _keepalive_task
    _keepalive_task = asyncio.create_task(_keepalive_loop(lk))
    url = f"{FWS_BASE}/ws/{lk}"
    backoff = 1.5
    while _running:
        try:
            async with websockets.connect(
                url,
                ping_interval=WS_KEEPALIVE_SEC,
                ping_timeout=10,
                close_timeout=5,
            ) as ws:
                backoff = 1.5
                while _running:
                    raw = await ws.recv()
                    data = json.loads(raw)
                    if str(data.get("e", "")).upper() == "ORDER_TRADE_UPDATE":
                        o = data.get("o") or {}
                        if _is_reduce_only_tp(o):
                            sym = str(o.get("s") or "").upper()
                            side = str(o.get("S") or "")
                            label = str(o.get("c") or "")
                            fp = float(o.get("ap") or o.get("sp") or o.get("p") or 0.0)
                            try:
                                await _on_tp(sym, side, fp, label)
                            except Exception as e:
                                logger.warning(
                                    {"event": "tp_handler_error", "symbol": sym, "err": str(e)}
                                )
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning({"event": "user_ws_error", "error": str(e)})
            await asyncio.sleep(min(60.0, backoff))
            backoff *= 1.7

# ===== Public API =====
async def start_user_stream_consumer():
    global _running, _ws_task
    if _running:
        return
    _running = True
    loop = asyncio.get_event_loop()
    _ws_task = loop.create_task(_consumer())
    logger.info({"event": "user_stream_started"})

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
    logger.info({"event": "user_stream_stopped"})

