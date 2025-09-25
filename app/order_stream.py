# app/order_stream.py
from __future__ import annotations
import os, json, time, asyncio, logging
from typing import Dict, Any, Optional

import httpx
import websockets

from telegram.commands import send_message

log = logging.getLogger("algogpt.order_stream")

BINANCE_FUTURES_HTTP_BASE = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com").rstrip("/")
BINANCE_FUTURES_WS_BASE = os.getenv("BINANCE_FUTURES_WS_BASE", "wss://fstream.binance.com").rstrip("/")
API_KEY     = os.getenv("BINANCE_API_KEY", "").strip()
API_SECRET  = os.getenv("BINANCE_API_SECRET", "").strip()  # לא נדרש ל-listenKey
TELEGRAM_CHAT_ID = int(os.getenv("TELEGRAM_CHAT_ID", "0") or "0")

LISTENKEY_REFRESH_SEC = 30 * 60  # 30 דקות (ביננס ממליצים)
_WS_RETRY_MIN = 3
_WS_RETRY_MAX = 60

class _ListenKey:
    key: Optional[str] = None
    ts: float = 0.0

LK = _ListenKey()

async def _create_listen_key() -> Optional[str]:
    if not API_KEY:
        log.warning("BINANCE_API_KEY missing; cannot create listenKey")
        return None
    url = f"{BINANCE_FUTURES_HTTP_BASE}/fapi/v1/listenKey"
    try:
        async with httpx.AsyncClient(timeout=10.0) as cli:
            r = await cli.post(url, headers={"X-MBX-APIKEY": API_KEY})
            r.raise_for_status()
            data = r.json()
            k = data.get("listenKey")
            if k:
                LK.key = k
                LK.ts = time.time()
                log.info("listenKey created")
                return k
    except Exception as e:
        log.error("create listenKey failed: %s", e)
    return None

async def _keepalive_listen_key() -> None:
    if not API_KEY or not LK.key:
        return
    if time.time() - LK.ts < LISTENKEY_REFRESH_SEC - 30:
        return
    url = f"{BINANCE_FUTURES_HTTP_BASE}/fapi/v1/listenKey"
    try:
        async with httpx.AsyncClient(timeout=10.0) as cli:
            r = await cli.put(url, headers={"X-MBX-APIKEY": API_KEY}, params={"listenKey": LK.key})
            if r.status_code == 200:
                LK.ts = time.time()
                log.debug("listenKey keepalive ok")
            else:
                log.warning("listenKey keepalive non-200: %s %s", r.status_code, r.text[:120])
    except Exception as e:
        log.warning("listenKey keepalive failed: %s", e)

def _fmt_price(p: Any) -> str:
    try:
        return f"{float(p):g}"
    except Exception:
        return str(p)

async def _notify(txt: str, parse: Optional[str] = "HTML") -> None:
    if not TELEGRAM_CHAT_ID:
        return
    try:
        await send_message(TELEGRAM_CHAT_ID, txt, parse)
    except Exception as e:
        log.warning("telegram notify failed: %s", e)

def _describe_event(o: Dict[str, Any]) -> str:
    # Futures user stream payload (ORDER_TRADE_UPDATE):
    # o keys examples: s=symbol, S=BUY/SELL, x=executionType, X=orderStatus, q=origQty, z=accumulatedFillQty,
    # p=price, ap=avgPrice, sp=stopPrice, ot=orderType, ps=positionSide, rp=realizedPnl, i=orderId
    s  = o.get("s"); side = o.get("S"); otype = o.get("ot")
    ex = o.get("x"); st = o.get("X")
    q  = o.get("q"); z = o.get("z"); p = o.get("p"); ap = o.get("ap")
    sp = o.get("sp"); ps = o.get("ps"); oid = o.get("i")
    rp = o.get("rp")

    # זיהוי TP/SL לפי orderType או לפי stopPrice קיים
    tag = ""
    if otype and "PROFIT" in str(otype):
        tag = " (TP)"
    elif otype and "STOP" in str(otype):
        tag = " (SL)"

    base = f"<b>{s}</b> {side} {tag} ps={ps or 'BOTH'}"
    if st == "FILLED":
        return f"🎯 FILLED {base} qty={z}/{q} @ {_fmt_price(ap or p)} · oid={oid}"
    if st == "PARTIALLY_FILLED":
        return f"🧩 PARTIAL {base} filled={z}/{q} lastP={_fmt_price(p)} · oid={oid}"
    if st == "CANCELED":
        return f"🛑 CANCELED {base} (stop={_fmt_price(sp)}) · oid={oid}"
    if ex == "NEW" and st == "NEW":
        return f"📌 NEW {base} q={q} p={_fmt_price(p)} stop={_fmt_price(sp)} · oid={oid}"
    # generic
    return f"ℹ️ {ex}/{st} {base} q={q} z={z} p={_fmt_price(p)} sp={_fmt_price(sp)} ap={_fmt_price(ap)} rp={rp} · oid={oid}"

async def _on_message(msg: Dict[str, Any]) -> None:
    # We care about `e == ORDER_TRADE_UPDATE`
    evt = msg.get("e")
    if evt != "ORDER_TRADE_UPDATE":
        return
    o = (msg.get("o") or {})
    await _notify(_describe_event(o))

async def _ws_loop() -> None:
    retry = _WS_RETRY_MIN
    while True:
        try:
            if not LK.key:
                k = await _create_listen_key()
                if not k:
                    await asyncio.sleep(retry)
                    retry = min(_WS_RETRY_MAX, retry * 2)
                    continue
            url = f"{BINANCE_FUTURES_WS_BASE}/ws/{LK.key}"
            log.info("connecting user stream WS: %s", url)
            async with websockets.connect(url, ping_interval=15, ping_timeout=20) as ws:
                retry = _WS_RETRY_MIN
                await _notify("✅ User stream connected")
                while True:
                    await _keepalive_listen_key()
                    raw = await asyncio.wait_for(ws.recv(), timeout=30.0)
                    try:
                        msg = json.loads(raw)
                    except Exception:
                        continue
                    await _on_message(msg)
        except asyncio.TimeoutError:
            # keepalive and loop
            continue
        except Exception as e:
            log.warning("WS disconnected: %s", e)
            await _notify("⚠️ User stream disconnected; retrying…")
            await asyncio.sleep(retry)
            retry = min(_WS_RETRY_MAX, retry * 2)

async def start_user_stream() -> None:
    """Public entry to be scheduled in background."""
    # defensive: ensure API key exists
    if not API_KEY:
        log.warning("No BINANCE_API_KEY; user stream disabled")
        return
    # prime listenKey
    await _create_listen_key()
    # run the loop forever
    await _ws_loop()

