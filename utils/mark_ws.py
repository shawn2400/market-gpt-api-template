# utils/mark_ws.py
from __future__ import annotations
import asyncio
import json
from typing import Dict, Optional

import aiohttp

WS_URL = "wss://fstream.binance.com/stream?streams=!markPrice@arr"

class MarkPriceBus:
    """
    מאזין יחיד ל-!markPrice@arr ושומר cache של מחירי Mark לפי סימבול.
    שימוש:
        from utils.mark_ws import bus
        bus.start()  # ב-startup
        price = bus.get("BTCUSDT")
    """
    def __init__(self) -> None:
        self._prices: Dict[str, float] = {}
        self._task: Optional[asyncio.Task] = None
        self._stop_evt = asyncio.Event()
        self._lock = asyncio.Lock()

    async def _run(self) -> None:
        backoff = 1.0
        while not self._stop_evt.is_set():
            try:
                async with aiohttp.ClientSession() as sess:
                    async with sess.ws_connect(WS_URL, heartbeat=20) as ws:
                        backoff = 1.0  # הצליח – אפס את הבקאוף
                        while not self._stop_evt.is_set():
                            msg = await ws.receive()
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                try:
                                    j = json.loads(msg.data)
                                    # מבנה: {"stream":"!markPrice@arr","data":[{ "s":"BTCUSDT", "p":"12345.6", ...}, ...]}
                                    arr = j.get("data") or []
                                    if isinstance(arr, list):
                                        async with self._lock:
                                            for it in arr:
                                                s = str(it.get("s") or "").upper()
                                                p = it.get("p")
                                                if s and p is not None:
                                                    try:
                                                        self._prices[s] = float(p)
                                                    except Exception:
                                                        pass
                                except Exception:
                                    # בולע שגיאה במסר בודד, ממשיך
                                    pass
                            elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                                break
            except Exception:
                # נסיון חיבור נכשל / נפל – המתן וגבה בקאוף
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2.0, 30.0)
                continue

    def start(self) -> None:
        """הפעל מאזין אם לא פעיל. בטוח לקריאה כפולה."""
        if self._task and not self._task.done():
            return
        loop = asyncio.get_event_loop()
        self._stop_evt.clear()
        self._task = loop.create_task(self._run())

    def stop(self) -> None:
        """עצירה נקייה."""
        if self._task:
            self._stop_evt.set()

    def get(self, symbol: str) -> Optional[float]:
        """החזר Mark Price אחרון או None אם לא קיים."""
        return self._prices.get(symbol.upper())

# אובייקט יחיד לשימוש האפליקציה
bus = MarkPriceBus()

