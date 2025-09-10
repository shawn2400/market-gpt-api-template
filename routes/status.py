# routes/status.py
from __future__ import annotations
import os, time
from typing import Dict, Any
from fastapi import APIRouter

router = APIRouter(prefix="", tags=["status"])

def _bool_env(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).lower() in ("1", "true", "yes", "on")

@router.get("/executor/status")
async def executor_status():
    # מקור ראשון: מהמודול
    try:
        from utils.auto_executor import get_executor_status
        exec_stat = get_executor_status()
    except Exception:
        exec_stat = {}

    # Snapshot של מדדים (P50/P95/P99)
    try:
        from utils.metrics import metrics_tracker
        metrics = metrics_tracker.get_snapshot()
    except Exception:
        metrics = {}

    return {
        "ok": True,
        "ts": time.time(),
        "executor": exec_stat,
        "metrics": metrics,
    }

@router.get("/ws-user/status")
async def ws_user_status():
    # נסה סטטוס מהמודול הייעודי אם קיים
    ws_stat: Dict[str, Any] = {}
    try:
        # מודול סטטוס פנימי (אופציונלי, מעודכן ע"י רכיבים שונים אם משתמשים)
        from utils.status import get_ws_user_status
        ws_stat = get_ws_user_status() or {}
    except Exception:
        ws_stat = {}

    # נסה סטטוס מ- ws_user_stream אם יש
    if not ws_stat:
        try:
            from utils import ws_user_stream  # type: ignore
            if hasattr(ws_user_stream, "get_status"):
                ws_stat = ws_user_stream.get_status() or {}
        except Exception:
            pass

    # TTL fallback לדוגמית סמלים
    ttl_samples: Dict[str, float] = {}
    try:
        from utils import ws_fallback
        syms = os.getenv("HEALTH_SYMBOLS", "BTCUSDT,ETHUSDT").split(",")
        for s in [x.strip().upper() for x in syms if x.strip()]:
            try:
                ttl = ws_fallback.get_price_age(s)
                if ttl is not None:
                    ttl_samples[s] = float(ttl)
            except Exception:
                continue
    except Exception:
        pass

    # “Degrade mode” חיש־פשוט לפי env (אינדיקציה)
    degrade = (
        os.getenv("BINANCE_WORKING_TYPE", "").upper() == "MARK_PRICE"
        and _bool_env("FEAT_MARK_INDEX_SANITY", "0")
    )

    return {
        "ok": True,
        "ts": time.time(),
        "ws": ws_stat,
        "ttl_samples": ttl_samples,
        "degrade_mode": degrade,
    }



