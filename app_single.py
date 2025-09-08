# app_single.py
from __future__ import annotations
import os, asyncio, time, json, logging, random
from typing import Dict, Any, Optional, List

import httpx
import websockets
from fastapi import FastAPI
from fastapi.responses import JSONResponse

# ===== Logging =====
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper())
log = logging.getLogger("app_single")

# ===== ENV =====
try:
    from dotenv import load_dotenv  # type: ignore
    if not (os.getenv("RENDER") or os.getenv("DYNO") or os.getenv("K_SERVICE")):
        load_dotenv(override=False)
except Exception:
    pass

PORT = int(os.getenv("PORT","10000"))
WATCHLIST = [s.strip().upper() for s in (os.getenv("WATCHLIST","BTCUSDT,ETHUSDT,SOLUSDT")).split(",") if s.strip()]
WS_KEEPALIVE_SEC = int(os.getenv("WS_KEEPALIVE_SEC","25"))
PRICE_MAX_AGE_SEC = int(os.getenv("PRICE_MAX_AGE_SEC","10"))

# Binance
BINANCE_API_KEY    = (os.getenv("BINANCE_API_KEY") or "").strip()
BINANCE_API_SECRET = (os.getenv("BINANCE_API_SECRET") or "").strip()
BINANCE_FAPI_HTTP  = (os.getenv("BINANCE_FUTURES_HTTP_BASE") or "https://fapi.binance.com").rstrip("/")
BINANCE_FWS_BASE   = (os.getenv("BINANCE_FUTURES_WS_BASE") or "wss://fstream.binance.com").rstrip("/")

# ===== In-Memory price cache =====
LAST_PRICE_CACHE: Dict[str, Dict[str, Any]] = {}  # {SYMBOL: {"price": float, "ts": epoch}}
def price_update(symbol: str, price: float) -> None:
    try:
        p = float(price)
        if p > 0:
            LAST_PRICE_CACHE[symbol.upper()] = {"price": p, "ts": time.time()}
    except Exception:
        pass

def price_get(symbol: str) -> Optional[float]:
    itm = LAST_PRICE_CACHE.get(symbol.upper())
    return float(itm["price"]) if itm and "price" in itm else None

def price_fresh(symbol: str, max_age: int = PRICE_MAX_AGE_SEC) -> bool:
    itm = LAST_PRICE_CACHE.get(symbol.upper())
    return bool(itm and (time.time() - float(itm.get("ts",0))) <= max_age)

# ===== WS price stream + REST fallback =====
async def _ws_price_stream(symbols: List[str], ping_interval: int = WS_KEEPALIVE_SEC) -> None:
    streams = "/".join(f"{s.lower()}@markPrice@1s" for s in symbols)
    url = f"{BINANCE_FWS_BASE}/stream?streams={streams}"
    backoff = 1.5
    while True:
        try:
            log.info({"event":"ws_connecting","url":url,"symbols":len(symbols)})
            async with websockets.connect(
                url, ping_interval=ping_interval, ping_timeout=10, close_timeout=5, max_size=1_000_000
            ) as ws:
                backoff = 1.5
                last_ping = time.time()
                while True:
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=ping_interval + 5)
                        data = json.loads(msg)
                        d = data.get("data") or {}
                        sym = d.get("s")
                        price = d.get("p") or d.get("markPrice") or d.get("price")
                        if sym and price:
                            price_update(sym, float(price))
                        if (time.time() - last_ping) >= ping_interval:
                            try:
                                await ws.ping()
                            except Exception:
                                break
                            last_ping = time.time()
                    except asyncio.TimeoutError:
                        try:
                            await ws.ping(); last_ping = time.time()
                        except Exception:
                            log.warning({"event":"ws_ping_failed"}); break
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.error({"event":"ws_connect_error","error":str(e)})
            await asyncio.sleep(backoff + random.uniform(0,0.8))
            backoff = min(backoff*2, 60.0)

async def _rest_price_refresher_loop(symbols: List[str], period: int = 15) -> None:
    target = set(s.upper() for s in symbols)
    async with httpx.AsyncClient(
        timeout=8.0,
        headers={"User-Agent":"AlgoGPT/2 price-fallback","Accept":"application/json","Accept-Encoding":"gzip"},
    ) as x:
        while True:
            try:
                r = await x.get(f"{BINANCE_FAPI_HTTP}/fapi/v1/premiumIndex")
                if r.status_code == 200:
                    for o in (r.json() or []):
                        sym = str(o.get("symbol") or "").upper()
                        if sym in target:
                            price = o.get("markPrice") or o.get("price")
                            try:
                                p = float(price)
                                if p > 0: price_update(sym, p)
                            except Exception:
                                pass
                elif r.status_code in (418,429,500,502,503,504):
                    retry = int(r.headers.get("Retry-After","2")); await asyncio.sleep(min(30, max(2,retry)))
                else:
                    r.raise_for_status()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.error({"event":"rest_fallback_iter_error","error":str(e)})
            await asyncio.sleep(period)

async def auto_price_updater(symbols: List[str], ws_keepalive: int = WS_KEEPALIVE_SEC, rest_interval: int = 15) -> None:
    syms = [s.upper() for s in symbols if s and s.strip()]
    if not syms:
        log.warning({"event":"price_updater_empty_symbols"}); return
    ws_task = None; rest_task = None
    try:
        while True:
            try:
                if rest_task and not rest_task.done():
                    rest_task.cancel()
                ws_task = asyncio.create_task(_ws_price_stream(syms, ping_interval=ws_keepalive))
                await ws_task
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.error({"event":"ws_stream_error","error":str(e)})
            try:
                rest_task = asyncio.create_task(_rest_price_refresher_loop(syms, period=rest_interval))
                await asyncio.sleep(min(60, 5 + random.uniform(0,3)))
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.error({"event":"rest_fallback_error","error":str(e)})
                await asyncio.sleep(5)
    finally:
        for t in (ws_task, rest_task):
            if t and not t.done(): t.cancel()

# ===== Minimal Binance helpers (HTTP) =====
async def fapi_ping() -> bool:
    try:
        async with httpx.AsyncClient(timeout=5.0) as x:
            r = await x.get(f"{BINANCE_FAPI_HTTP}/fapi/v1/ping")
            return r.status_code == 200
    except Exception:
        return False

async def futures_balance_ok() -> bool:
    """בריאות בלבד – לא מציג נתונים רגישים."""
    try:
        headers = {"X-MBX-APIKEY": BINANCE_API_KEY}
        async with httpx.AsyncClient(timeout=8.0) as x:
            r = await x.get(f"{BINANCE_FAPI_HTTP}/fapi/v2/balance", headers=headers)
            return r.status_code == 200 and isinstance(r.json(), list)
    except Exception:
        return False

# ===== User-Data Stream (TP→SL-BE) בסיסי =====
_running_stream = False
_keepalive_task: Optional[asyncio.Task] = None

async def _listen_key() -> str:
    headers = {"X-MBX-APIKEY": BINANCE_API_KEY, "Accept":"application/json"}
    async with httpx.AsyncClient(timeout=8.0) as x:
        r = await x.post(f"{BINANCE_FAPI_HTTP}/fapi/v1/listenKey", headers=headers)
        r.raise_for_status()
        lk = (r.json() or {}).get("listenKey")
        if not lk: raise RuntimeError("no listenKey")
        return lk

async def _keepalive_listen_key(lk: str):
    headers = {"X-MBX-APIKEY": BINANCE_API_KEY, "Accept":"application/json"}
    async with httpx.AsyncClient(timeout=8.0) as x:
        while _running_stream:
            try:
                await x.put(f"{BINANCE_FAPI_HTTP}/fapi/v1/listenKey", headers=headers)
            except Exception as e:
                log.warning({"event":"listenkey_keepalive_error","error":str(e)})
            await asyncio.sleep(int(os.getenv("LISTENKEY_KEEPALIVE_SEC","1800")))

def _is_tp_fill(o: Dict[str, Any]) -> bool:
    ty = str(o.get("o","")).upper()
    st = str(o.get("X","")).upper()
    return ty.startswith("TAKE_PROFIT") and st in ("FILLED","PARTIALLY_FILLED")

async def _set_sl_close_position(symbol: str, side: str, stop_price: float) -> None:
    """פשטות: SL כ-closePosition=True (מקטין שגיאות טיקים/כמות)."""
    side_close = "SELL" if side.upper() in ("BUY","LONG") else "BUY"
    headers = {"X-MBX-APIKEY": BINANCE_API_KEY, "Accept":"application/json"}
    payload = {
        "symbol": symbol.upper(),
        "side": side_close,
        "type": "STOP_MARKET",
        "stopPrice": f"{float(stop_price):.8f}",
        "reduceOnly": "true",
        "closePosition": "true",
        "newClientOrderId": f"SL_BE_{symbol.upper()}_{int(time.time()*1000)}",
        "recvWindow": "45000",
        "workingType": os.getenv("BINANCE_WORKING_TYPE","MARK_PRICE"),
    }
    async with httpx.AsyncClient(timeout=8.0) as x:
        try:
            await x.post(f"{BINANCE_FAPI_HTTP}/fapi/v1/order", headers=headers, data=payload)
            log.info({"event":"sl_be_set","symbol":symbol})
        except Exception as e:
            log.warning({"event":"sl_be_set_failed","symbol":symbol,"err":str(e)})

async def _user_stream_consumer():
    if not (BINANCE_API_KEY and BINANCE_API_SECRET):
        log.warning("BINANCE API keys missing; user-data stream disabled.")
        return
    lk = await _listen_key()
    global _keepalive_task
    _keepalive_task = asyncio.create_task(_keepalive_listen_key(lk))
    url = f"{BINANCE_FWS_BASE}/ws/{lk}"
    backoff = 1.5
    while _running_stream:
        try:
            async with websockets.connect(url, ping_interval=WS_KEEPALIVE_SEC, ping_timeout=10, close_timeout=5) as ws:
                backoff = 1.5
                while _running_stream:
                    raw = await ws.recv()
                    data = json.loads(raw)
                    if str(data.get("e","")).upper() == "ORDER_TRADE_UPDATE":
                        o = data.get("o") or {}
                        if _is_tp_fill(o):
                            sym  = str(o.get("s") or "").upper()
                            side = str(o.get("S") or "")
                            ap   = float(o.get("ap") or o.get("sp") or o.get("p") or 0.0)
                            # ברירת מחדל: קבע SL במחיר המילוי של ה-TP (אפשר לשנות ל-BE אמיתי לפי entry)
                            asyncio.create_task(_set_sl_close_position(sym, side, ap))
        except asyncio.CancelledError:
            break
        except Exception as e:
            log.warning({"event":"user_ws_error","error":str(e)})
            await asyncio.sleep(min(60.0, backoff)); backoff *= 1.7

async def start_user_stream():
    global _running_stream
    if _running_stream: return
    _running_stream = True
    asyncio.create_task(_user_stream_consumer())
    log.info({"event":"user_stream_started"})

async def stop_user_stream():
    global _running_stream, _keepalive_task
    _running_stream = False
    try:
        if _keepalive_task and not _keepalive_task.done(): _keepalive_task.cancel()
    except Exception: pass
    _keepalive_task = None
    log.info({"event":"user_stream_stopped"})

# ===== FastAPI =====
app = FastAPI(title="AlgoGPT Single", version=os.getenv("ALGOGPT_VERSION","single"))

@app.get("/")
async def root():
    return {"ok": True, "service": "app_single", "watchlist": WATCHLIST}

@app.get("/health")
async def health():
    return {"ok": True, "ts": time.time()}

@app.get("/readyz")
async def readyz():
    details: Dict[str, Any] = {}
    try:
        details["ping_ok"] = await fapi_ping()
        details["balance_ok"] = await futures_balance_ok()
        syms = WATCHLIST or ["BTCUSDT","ETHUSDT","SOLUSDT"]
        for s in syms:
            details[f"price_{s}"] = price_fresh(s)
        ok = bool(details["ping_ok"] and details["balance_ok"] and all(details[k] for k in details if k.startswith("price_")))
        return {"ok": ok, "details": details}
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e), "details": details})

@app.get("/price/{symbol}")
async def price(symbol: str):
    p = price_get(symbol)
    return {"symbol": symbol.upper(), "price": p, "fresh": price_fresh(symbol)}

# ===== lifecycle =====
@app.on_event("startup")
async def on_startup():
    log.info({"event":"startup","watchlist":WATCHLIST})
    try:
        asyncio.create_task(auto_price_updater(WATCHLIST, ws_keepalive=WS_KEEPALIVE_SEC, rest_interval=15))
    except Exception:
        pass
    try:
        asyncio.create_task(start_user_stream())
    except Exception:
        pass

@app.on_event("shutdown")
async def on_shutdown():
    try:
        await stop_user_stream()
    except Exception:
        pass

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app_single:app", host=os.getenv("BIND_HOST","0.0.0.0"), port=PORT)

