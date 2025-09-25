# app/order_stream.py
from __future__ import annotations
import os, json, asyncio, logging
from typing import Dict, Any
import httpx

from telegram.commands import send_message

log = logging.getLogger("algogpt.order_stream")
TELEGRAM_CHAT_ID = int(os.getenv("TELEGRAM_CHAT_ID","0") or "0")
BINANCE_FUTURES_WS_BASE = os.getenv("BINANCE_FUTURES_WS_BASE", "wss://fstream.binance.com")
LISTEN_KEY = None  # תצטרך ליצור listenKey דרך ה-REST ולרענן כל 30 דק'

async def _keepalive_listen_key():
    # TODO: הוסף קריאות REST ל-POST /fapi/v1/listenKey + PUT לשימור.
    pass

async def _consume_user_stream():
    if not LISTEN_KEY:
        log.warning("No LISTEN_KEY set; skipping user stream")
        return
    url = f"{BINANCE_FUTURES_WS_BASE}/stream?streams={LISTEN_KEY}"
    async with httpx.AsyncClient(timeout=None) as cli:
        async with cli.stream("GET", url) as r:
            async for b in r.aiter_bytes():
                try:
                    data = json.loads(b.decode("utf-8"))
                except Exception:
                    continue
                ev = (data.get("data") or {})
                if ev.get("e") == "ORDER_TRADE_UPDATE":
                    o = (ev.get("o") or {})
                    s = o.get("s"); X = o.get("X")  # FILLED/NEW/CANCELED/...
                    S = o.get("S")  # BUY/SELL
                    q = o.get("q"); p = o.get("p")  # qty/price
                    if X == "FILLED" and TELEGRAM_CHAT_ID:
                        await send_message(TELEGRAM_CHAT_ID, f"🎯 FILLED {S} {s} qty={q} @ {p}")
                # הוסף STOP/TPS Triggered לפי סוג order
async def main():
    asyncio.create_task(_keepalive_listen_key())
    await _consume_user_stream()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
