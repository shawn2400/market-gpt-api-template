# routes/scheduler_ai.py
from __future__ import annotations
import os, asyncio
from typing import List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException
import httpx

from utils.auth import require_api_key

router = APIRouter(prefix="/ai_sched", tags=["AI-Scheduler"], dependencies=[Depends(require_api_key)])

_task: asyncio.Task | None = None
_running: bool = False

def _bearer() -> str:
    return f"Bearer {os.getenv('API_BEARER_TOKEN','').strip()}"

async def _loop():
    global _running
    interval = int(os.getenv("AI_SCHED_INTERVAL_SEC","300"))
    watch = [s.strip().upper() for s in (os.getenv("WATCHLIST","BTCUSDT,ETHUSDT").split(",")) if s.strip()]
    to_telegram = str(os.getenv("AI_QUEUE_TO_TELEGRAM","1")).lower() in ("1","true","yes","on")
    auto_exec   = str(os.getenv("AI_QUEUE_AUTO_EXECUTE","0")).lower() in ("1","true","yes","on")

    headers = {"Authorization": _bearer(), "Accept":"application/json"}
    while _running:
        try:
            req = {
                "symbols": watch,
                "interval": os.getenv("DEFAULT_INTERVAL","15m"),
                "market": os.getenv("DEFAULT_MARKET","futures"),
                "max_items": len(watch),
                "mode": "telegram" if to_telegram and not auto_exec else "sink",
                "queue_to_telegram": to_telegram,
                "auto_execute_sink": auto_exec,
            }
            async with httpx.AsyncClient(timeout=20.0) as client:
                r = await client.post("/ai/suggest_and_queue", json=req, headers=headers)
                # לא מפיל לולאה במקרה של שגיאה; רק מדלג לסיבוב הבא
        except Exception:
            pass
        await asyncio.sleep(max(30, interval))

@router.post("/start")
async def start():
    global _task, _running
    if _running: return {"ok": True, "status":"already-running"}
    _running = True
    loop = asyncio.get_event_loop()
    _task = loop.create_task(_loop())
    return {"ok": True, "status":"started"}

@router.post("/stop")
async def stop():
    global _task, _running
    _running = False
    if _task and not _task.done():
        _task.cancel()
    _task = None
    return {"ok": True, "status":"stopped"}

@router.get("/status")
async def status():
    return {"ok": True, "running": _running}
