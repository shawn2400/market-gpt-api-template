# routes/guard_smoke.py
from __future__ import annotations
import os, hmac, hashlib, time
from fastapi import APIRouter, Header, HTTPException, Depends, Query
from typing import Optional

from utils.smoke_checks import run_smoke_guard

router = APIRouter(tags=["ops-guard"], prefix="/guard")

API_BEARER_TOKEN = (os.getenv("API_BEARER_TOKEN") or os.getenv("PRIMARY_API_TOKEN") or "").strip()
OPS_SIGN_SECRET  = (os.getenv("OPS_SIGN_SECRET") or "").strip()

def _auth(bearer: Optional[str] = Header(default=None, alias="Authorization"),
          sig: Optional[str]    = Header(default=None, alias="X-OPS-Sign"),
          ts: Optional[str]     = Header(default=None, alias="X-OPS-Ts")):
    # 1) Bearer
    if API_BEARER_TOKEN and bearer and bearer.lower().startswith("bearer "):
        if bearer.split(" ",1)[1].strip() == API_BEARER_TOKEN:
            return True
    # 2) HMAC (X-OPS-Sign)
    if OPS_SIGN_SECRET and sig and ts:
        try:
            # signature over "ts:/guard/smoke/run"
            data = f"{ts}:/guard/smoke/run".encode()
            calc = hmac.new(OPS_SIGN_SECRET.encode(), data, hashlib.sha256).hexdigest()
            # anti-replay (30s)
            if abs(int(time.time()) - int(ts)) <= 30 and hmac.compare_digest(calc, sig):
                return True
        except Exception:
            pass
    raise HTTPException(status_code=401, detail="Unauthorized")

@router.post("/smoke/run")
def guard_smoke_run(send_report: bool = Query(default=True), _=Depends(_auth)):
    """
    מריץ Smoke-Guard: מבטיח SL פעיל על 100% בכל הסימבולים הפתוחים (או WATCHLIST),
    ומדווח לטלגרם אם בוצעו תיקונים/שגיאות.
    """
    res = run_smoke_guard(send_report=send_report)
    return res
