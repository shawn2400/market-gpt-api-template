# routes/ws_stream.py
from __future__ import annotations
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import asyncio, json
from utils.ws_fallback import get_price

router = APIRouter(prefix="/ws", tags=["WebSocket"])

@router.websocket("/stream")
async def ws_stream(ws: WebSocket):
    # קבלת query params ידנית
    symbols_param = ws.query_params.get("symbols", "")
    symbols_list = [s.strip().upper() for s in symbols_param.split(",") if s.strip()]

    await ws.accept()
    try:
        while True:
            data = {}
            for sym in symbols_list:
                price = get_price(sym)
                if price:
                    data[sym] = price
            await ws.send_text(json.dumps(data))
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        return

