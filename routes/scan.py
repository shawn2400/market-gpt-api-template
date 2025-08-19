# routes/scan.py
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Dict, List
from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(tags=["Scan"])

class ScanInfo(BaseModel):
    ok: bool = True
    now_utc: str
    executor_running: bool
    config: Dict[str, Any] = Field(default_factory=dict)
    notes: List[str] = Field(default_factory=list)

@router.get("/scan/info", response_model=ScanInfo, operation_id="getScanInfo")
def get_scan_info() -> ScanInfo:
    now = datetime.now(tz=timezone.utc).isoformat()
    try:
        from utils.auto_executor import is_executor_running  # type: ignore
        executor_running = bool(is_executor_running())
    except Exception:
        executor_running = False

    cfg: Dict[str, Any] = {}
    notes: List[str] = []

    try:
        from utils import config as c  # type: ignore
        for k in ("AUTO_RUN","SCAN_INTERVAL","MIN_QUALITY_SCORE","MAX_TRADE_BUDGET",
                  "TRENDING_ONLY","DEFAULT_INTERVAL"):
            if hasattr(c, k):
                cfg[k] = getattr(c, k)
    except Exception:
        notes.append("config module not loaded; using defaults")

    if not executor_running:
        notes.append("auto-executor is not running; set AUTO_RUN=true and restart")

    return ScanInfo(ok=True, now_utc=now, executor_running=executor_running, config=cfg, notes=notes)






