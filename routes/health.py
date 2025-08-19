# routes/health.py
from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(tags=["Health"])

# נשמר בזמן טעינת המודול לצורך חישוב uptime
_BOOT_TS = int(time.time())


# ====== Models (לנוחות/תיעוד; ה־OpenAPI שלך מאפשר additionalProperties) ======
class BasicStatus(BaseModel):
    status: str = Field("ok", examples=["ok"])
    version: str = Field(..., examples=["2.14.3"])


class LiveStatus(BaseModel):
    status: str = Field("live", examples=["live"])
    uptime_sec: int = Field(..., ge=0)
    now_utc: str = Field(..., examples=["2025-08-19T10:32:23.074820+00:00"])
    # שדות נוספים מותרים לפי ה־OpenAPI (additionalProperties: true)


class StrategyVersion(BaseModel):
    algogpt_version: Optional[str] = None
    strategy_version: Optional[str] = None
    git_commit: Optional[str] = None
    requirements_hash: Optional[str] = None
    python_version: Optional[str] = None
    notes: Optional[str] = None


# ====== Endpoints ======
@router.get("/health", response_model=BasicStatus, operation_id="getBasicHealth")
def health() -> BasicStatus:
    """
    בדיקת בריאות בסיסית. תואם להגדרה ב־OpenAPI (status + version).
    """
    return BasicStatus(
        status="ok",
        version=os.getenv("ALGOGPT_VERSION", "unknown"),
    )


@router.get("/health/live", response_model=LiveStatus, operation_id="getLiveness")
def liveness() -> Dict[str, Any]:
    """
    Liveness / Uptime. תמיד מחזיר 200 עם זמן ריצה ונקודת זמן נוכחית ב־UTC.
    """
    now_iso = datetime.now(tz=timezone.utc).isoformat()
    return {
        "status": "live",
        "uptime_sec": int(time.time()) - _BOOT_TS,
        "now_utc": now_iso,
    }


@router.get("/health/strategy-version", response_model=StrategyVersion, operation_id="getStrategyVersion")
def strategy_version() -> StrategyVersion:
    """
    מטא־דאטה של הגרסה/תלויות. additionalProperties מותרים בסכימה שלך,
    לכן מחזירים רק שדות ידידותיים בלי להציף מידע רגיש.
    """
    try:
        import sys
        pyver = sys.version.split()[0]
    except Exception:
        pyver = None

    return StrategyVersion(
        algogpt_version=os.getenv("ALGOGPT_VERSION"),
        strategy_version=os.getenv("STRATEGY_VERSION"),
        git_commit=os.getenv("GIT_COMMIT"),
        requirements_hash=os.getenv("REQ_HASH"),
        python_version=pyver,
        notes=None,
    )













