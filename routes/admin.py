# routes/admin.py
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from typing import Dict, Any
import os, hmac, hashlib
import httpx, logging

from utils.auth import require_api_key
from utils.config import dump_config_sanitized
from utils.time_sync import ensure_fresh_sync, last_server_time_ms, server_time_ms, recv_window_ms
from utils.feature_flags import set_flag
from utils.auto_executor import is_executor_running

router = APIRouter(prefix="/admin", tags=["Admin"], dependencies=[Depends(require_api_key)])
log = logging.getLogger("algogpt.admin")

_PAUSED = False

def _bool_env(name: str, default: bool=False) -> bool:
    v = os.getenv(name)
    if v is None: return default
    return str(v).strip().lower() in ("1","true","yes","on")

@router.post("/panic")
def panic_pause():
    """Pause גלובלי מיידי (שלב ב’)."""
    global _PAUSED
    _PAUSED = True
    os.environ["PAUSE_AUTO_RUN"] = "1"
    log.warning({"event": "panic_pause", "by": "admin"})
    return {"ok": True, "paused": True}

@router.post("/resume")
def panic_resume():
    global _PAUSED
    _PAUSED = False
    os.environ["PAUSE_AUTO_RUN"] = "0"
    log.info({"event": "panic_resume", "by": "admin"})
    return {"ok": True, "paused": False}

@router.get("/status")
def admin_status():
    ensure_fresh_sync()
    ready = {
        "time_sync_ok": last_server_time_ms() is not None,
        "executor_running": bool(is_executor_running()),
        "paused": bool(_PAUSED or _bool_env("PAUSE_AUTO_RUN", False)),
    }
    return {"ok": True, "ready": ready, "version": os.getenv("ALGOGPT_VERSION","?")}

@router.get("/positions")
def positions_snapshot() -> Dict[str, Any]:
    """
    Snapshot פוזיציות (read-only). מחזיר רק כמות לא־אפס.
    """
    base = (os.getenv("BINANCE_FUTURES_HTTP_BASE") or "https://fapi.binance.com").rstrip("/")
    key  = (os.getenv("BINANCE_API_KEY") or "").strip()
    sec  = (os.getenv("BINANCE_API_SECRET") or "").strip()
    if not key or not sec:
        raise HTTPException(400, "Missing BINANCE_API_KEY/SECRET")

    ts = int(server_time_ms()); rw = int(recv_window_ms())
    q = f"timestamp={ts}&recvWindow={rw}"
    sig = hmac.new(sec.encode(), q.encode(), hashlib.sha256).hexdigest()
    params = {"timestamp": ts, "recvWindow": rw, "signature": sig}
    headers = {"X-MBX-APIKEY": key, "Accept":"application/json"}

    url = f"{base}/fapi/v2/positionRisk"
    with httpx.Client(timeout=6.0, headers=headers) as c:
        r = c.get(url, params=params)
        try:
            r.raise_for_status()
        except Exception as e:
            raise HTTPException(r.status_code, f"binance error: {e}; body={r.text}")

        items = []
        for p in r.json():
            try:
                amt = float(p.get("positionAmt") or 0.0)
                if abs(amt) < 1e-12:
                    continue
                items.append({
                    "symbol": p.get("symbol"),
                    "positionAmt": float(p.get("positionAmt")),
                    "entryPrice": float(p.get("entryPrice") or 0.0),
                    "unRealizedProfit": float(p.get("unRealizedProfit") or 0.0),
                    "leverage": int(float(p.get("leverage") or 0)),
                    "marginType": p.get("marginType"),
                    "side": "LONG" if float(p.get("positionAmt") or 0) > 0 else "SHORT",
                })
            except Exception:
                continue
        return {"ok": True, "items": items}

@router.get("/config/show")
def config_show():
    return {"ok": True, "config": dump_config_sanitized()}

@router.post("/flag/{name}/{value}")
def set_feature_flag(name: str, value: str):
    """הדלקה/כיבוי דגל בזמן ריצה (Override בזיכרון)."""
    v = value.strip().lower() in ("1","true","yes","on")
    set_flag(name, v)
    return {"ok": True, "name": name, "value": v}
