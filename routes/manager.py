# routes/manager.py
from __future__ import annotations
import os, json, time, glob, hashlib, asyncio, logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger("algogpt.manager")
router = APIRouter(tags=["manager"])

# ---- Config / Paths ----
BASE_DIR   = Path(os.getenv("BASE_DIR", "/opt/render/project/src"))
INGEST_DIR = Path(os.getenv("INGEST_DIR", str(BASE_DIR / "static" / "cache")))
MANAGER_ENABLE       = os.getenv("MANAGER_ENABLE", "1").lower() in ("1","true","yes","on")
MANAGER_INTERVAL_SEC = int(os.getenv("MANAGER_INTERVAL_SEC", "10"))

# ---- ConfirmStore (מ-utils.trade_executor) ----
try:
    from utils.trade_executor import ConfirmStore  # type: ignore
except Exception as e:
    logger.error("ConfirmStore missing: %s", e)
    class _Dummy:
        _P: Dict[str, Dict[str, Any]] = {}
        @classmethod
        def pending(cls) -> List[Dict[str, Any]]:
            return list(cls._P.values())
        @classmethod
        def create(cls, payload: Dict[str, Any]) -> str:
            tid = payload.get("ticket_id") or f"TKT-{int(time.time()*1000)}"
            payload["ticket_id"] = tid
            cls._P[tid] = payload
            return tid
        @classmethod
        def decide(cls, ticket_id: str, approved: bool) -> Dict[str, Any]:
            it = cls._P.pop(ticket_id, None)
            if not it: return {"ok": False, "error": "not_found"}
            return {"ok": True, "approved": approved, "ticket_id": ticket_id}
    ConfirmStore = _Dummy  # type: ignore

# ---- Models ----
class UpdateTicketReq(BaseModel):
    ticket_id: str
    action: str  # APPROVE | REJECT

# ---- Helpers ----
def _ticket_id_for(obj: Dict[str, Any]) -> str:
    key = {
        "symbol": obj.get("symbol"),
        "market": obj.get("market","futures"),
        "timeframe": obj.get("timeframe","15m"),
        "side": obj.get("side"),
        "reason": obj.get("reason",""),
        "score": obj.get("score",0.0),
        "require_approval": bool(obj.get("require_approval", True)),
        "entry": obj.get("entry","limit"),
        "risk_pct": obj.get("risk_pct", 0.5),
        "stop_loss_pct": obj.get("stop_loss_pct", 0.8),
        "take_profit_rr": obj.get("take_profit_rr", 1.6),
    }
    h = hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()[:16]
    return f"TKT-{h}"

def _load_ingests() -> List[Dict[str, Any]]:
    if not INGEST_DIR.is_dir():
        return []
    items: List[Dict[str, Any]] = []
    for p in sorted(INGEST_DIR.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True):
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(obj, dict): items.append(obj)
            elif isinstance(obj, list): items.extend([x for x in obj if isinstance(x, dict)])
        except Exception as e:
            logger.warning("ingest read failed: %s (%s)", p, e)
    return items

def _already_pending(tid: str) -> bool:
    try:
        return any((x.get("ticket_id") == tid) for x in ConfirmStore.pending())
    except Exception:
        return False

def _create_ticket(obj: Dict[str, Any]) -> Optional[str]:
    # דורש לפחות symbol+side
    if not obj.get("symbol") or not obj.get("side"):
        return None
    payload = {
        "ticket_id": _ticket_id_for(obj),
        "source": obj.get("source","ingest"),
        "symbol": obj.get("symbol"),
        "market": obj.get("market","futures"),
        "timeframe": obj.get("timeframe","15m"),
        "side": obj.get("side"),
        "score": float(obj.get("score", 0.0)),
        "reason": obj.get("reason",""),
        "entry_mode": obj.get("entry","limit"),
        "risk_pct": float(obj.get("risk_pct", 0.5)),
        "stop_loss_pct": float(obj.get("stop_loss_pct", 0.8)),
        "take_profit_rr": float(obj.get("take_profit_rr", 1.6)),
        "require_approval": bool(obj.get("require_approval", True)),
        "ts": int(time.time()),
    }
    tid = payload["ticket_id"]
    if _already_pending(tid):
        return None
    try:
        return ConfirmStore.create(payload) or tid
    except Exception as e:
        logger.error("ConfirmStore.create failed: %s", e)
        return None

async def _tick_once() -> Dict[str, Any]:
    created: List[str] = []
    for obj in _load_ingests():
        tid = _create_ticket(obj)
        if tid: created.append(tid)
    try:
        pend = ConfirmStore.pending()
    except Exception:
        pend = []
    return {"ok": True, "created": created, "pending_count": len(pend)}

# ---- Endpoints ----
@router.post("/manage-once")
async def manage_once():
    return await _tick_once()

@router.post("/ops/manager/tick")
async def ops_manager_tick():
    return await _tick_once()

@router.get("/alerts/trades/active")
async def alerts_trades_active():
    try:
        items = ConfirmStore.pending()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"ConfirmStore error: {e}")
    out: Dict[str, Any] = {}
    for it in items:
        tid = it.get("ticket_id") or _ticket_id_for(it)
        out[tid] = it
    return {"ok": True, "count": len(out), "items": out}

@router.post("/alerts/trades/update")
async def alerts_trades_update(req: UpdateTicketReq):
    act = req.action.upper().strip()
    if act not in ("APPROVE","REJECT"):
        raise HTTPException(status_code=400, detail="action must be APPROVE or REJECT")
    try:
        res = ConfirmStore.decide(req.ticket_id, approved=(act=="APPROVE"))
        return {"ok": True, "result": res}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"decision failed: {e}")

# ---- Background worker (optional) ----
async def _manager_loop():
    logger.info("manager_loop start: enable=%s interval=%ss ingest_dir=%s",
                MANAGER_ENABLE, MANAGER_INTERVAL_SEC, INGEST_DIR)
    while True:
        try:
            await _tick_once()
        except Exception as e:
            logger.error("manager_loop error: %s", e)
        await asyncio.sleep(max(3, MANAGER_INTERVAL_SEC))

@router.on_event("startup")
async def _startup():
    if MANAGER_ENABLE:
        asyncio.create_task(_manager_loop())
