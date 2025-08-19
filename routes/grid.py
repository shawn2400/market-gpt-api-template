# routes/grid.py
from __future__ import annotations

import time
from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

# אימות Bearer (עוקף אוטומטית אם SECURITY_ALLOW_ALL=1)
try:
    from utils.auth import require_bearer_token  # type: ignore
except Exception:
    def require_bearer_token():
        return None

router = APIRouter(tags=["Grid"], dependencies=[Depends(require_bearer_token)])

class GridStatus(BaseModel):
    ok: bool = True
    running: bool = False
    workers: int = 0
    queue_size: int = 0
    concurrency: int = 16
    last_heartbeat: Optional[str] = None
    notes: Optional[Dict[str, Any]] = Field(default=None)

def _try_get_status() -> Dict[str, Any]:
    """
    מנסה להביא סטטוס מ־utils.grid_tracker או utils.grid_executor אם קיים.
    לא זורק חריגות — תמיד יחזיר dict.
    """
    # 1) grid_tracker (עדיפות ראשונה אם קיים)
    try:
        from utils.grid_tracker import get_status as _grid_status  # type: ignore
        st = _grid_status() or {}
        if isinstance(st, dict):
            return st
    except Exception:
        pass

    # 2) grid_executor (חלופה) — אם יש פונקציית סטטוס
    try:
        from utils.grid_executor import get_status as _exec_status  # type: ignore
        st = _exec_status() or {}
        if isinstance(st, dict):
            return st
    except Exception:
        pass

    # 3) אין כלום — מצב ריק
    return {}

@router.get("/grid/status", response_model=GridStatus, operation_id="getGridStatus")
def get_grid_status() -> GridStatus:
    st = _try_get_status()

    # מיפוי בטוח עם ברירות מחדל
    running = bool(st.get("running", False))
    workers = int(st.get("workers", 0) or 0)
    qsize   = int(st.get("queue_size", 0) or 0)
    conc    = int(st.get("concurrency", 16) or 16)
    last_hb = st.get("last_heartbeat")
    # הערות: נחזיר מה שיש, ונוסיף זמן נוכחי לטרייסינג
    notes = st.get("notes") if isinstance(st.get("notes"), dict) else {}
    if isinstance(notes, dict):
        notes = {**notes, "ts": int(time.time())}

    return GridStatus(
        ok=True,
        running=running,
        workers=workers,
        queue_size=qsize,
        concurrency=conc,
        last_heartbeat=last_hb,
        notes=notes or None,
    )














