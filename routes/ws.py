# routes/ws.py
# =============
from __future__ import annotations
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import asyncio, json, logging
from typing import Dict, Any
from utils.ws_fallback import LAST_PRICE_CACHE

logger = logging.getLogger("algogpt.ws")
router = APIRouter(prefix="/ws", tags=["WebSocket"])

connections: Dict[str, WebSocket] = {}

@router.websocket("/stream")
async def ws_stream(ws: WebSocket):
    await ws.accept()
    cid = f"conn-{id(ws)}"
    connections[cid] = ws
    logger.info(f"[WS] Client connected: {cid}")
    try:
        while True:
            snapshot: Dict[str, Any] = {}
            for sym, info in list(LAST_PRICE_CACHE.items()):
                snapshot[sym] = {"price": info.get("price"), "ts": info.get("ts")}
            await ws.send_text(json.dumps({"event": "price_snapshot", "data": snapshot}))
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        logger.info(f"[WS] Client disconnected: {cid}")
    except Exception as e:
        logger.error(f"[WS] Error for {cid}: {e}")
    finally:
        connections.pop(cid, None)



