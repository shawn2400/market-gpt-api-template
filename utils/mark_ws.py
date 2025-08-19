# utils/mark_ws.py
from __future__ import annotations
import asyncio
import json
from typing import Dict, Optional

import aiohttp  # כבר קיים בתלויות אצלך

WS_URL = "wss://fstream.binance.com/stream?streams=!markPrice@arr"

class MarkPriceBus:
    def __init__(self):
        self._prices: Dict[str, float] = {}
        self._task: Optional[asyncio.Task] = None

    async def _run(self):
        while True:
            try:
                async with aiohttp.ClientSession() as sess:
                    async with sess.ws_connect(WS_URL, heartbeat=20) as ws:
                        async for msg in ws:
                            if msg.type != aiohttp.WSMsgType.TEXT:
                                continue
                            try
