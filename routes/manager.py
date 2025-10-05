# routes/manager.py
from __future__ import annotations
import os, json, time, hashlib, asyncio, logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx  # ← חדש: נדרש לשליחת ה-POST ל-/alerts/ingest
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger("algogpt.manager")
router = APIRouter(tags=["manager"])

# ---- Config / Paths ----
BASE_DIR   = Path(os.getenv("BASE_DIR", "/app"))
INGEST_DIR = Path(os.getenv("INGEST_DIR", str(BASE_DIR / "static" / "cache")))
MANAGER_ENABLE       = os.getenv("MANAGER_ENABLE", "1").lower() in ("1","true","yes","on")
MANAGER_INTERVAL_SEC = int(os.getenv("MANAGER_INTERVAL_SEC", "10"))

# ---- Alerts ingest target / auth ----
PUBLIC_HOST = (os.getenv("PUBLIC_HOST", "") or os.getenv("WEBHOOK_HOST", "")).rstrip("/")
ALERTS_INGEST_URL = os.getenv("ALERTS_INGEST_URL", f"{PUBLIC_HOST}/alerts/ingest").strip()
API_TOKEN = os.getenv("API_TOKEN", os.getenv("PRIMARY_API_TOKEN", "")).strip()

# ברירות מחדל כדי לעבור ולידציה בצד /alerts/ingest (גם אם דורשים אישור)
DEFAULT_QTY = float(os.getenv("DEFAULT_QTY", "0.001"))
DEFAULT_LEVERAGE = int(os.getenv("DEFAULT_LEVERAGE", "5"))

HTTP_TIMEOUT = float(os.getenv("MANAGER_HTTP_TIMEOUT", "10.0"))

# ---- ConfirmStore (מ-utils.trade_executor) – משמש *נפילה אחורה* בלבד ----
try:
    from utils.trade_executor import ConfirmStore  # type: ignore
except Exception as e:
    logger.error("ConfirmStore missing (fallback dummy will be used): %s", e)
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
        @classmethod
        def flush_all(cls) -> None:
            cls._P.clear()
        flush = reset = flush_all
    ConfirmStore = _Dummy  # type: ignore

# ---- Telemetry (גלובלי) ----
TICK_COUNT: int = 0
LAST_TICK_TS: int = 0
LAST_CREATED: List[str] = []
LAST_PENDING: int = 0
LAST_ERROR: Optional[str] = None

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

def _get_pending_safe() -> List[Dict[str, Any]]:
    """
    תומך בכל וריאציה של ConfirmStore:
    - מתודה pending() שמחזירה list[dict]
    - שדה dict בשם _P או pending
    - רשימה גולמית
    """
    try:
        if hasattr(ConfirmStore, "pending") and callable(getattr(ConfirmStore, "pending")):
            res = ConfirmStore.pending()  # type: ignore
            if isinstance(res, list): return [x for x in res if isinstance(x, dict)]
    except Exception:
        pass
    for attr in ("_P", "pending"):
        try:
            data = getattr(ConfirmStore, attr, None)
            if isinstance(data, dict): return list(data.values())
            if isinstance(data, list): return [x for x in data if isinstance(x, dict)]
        except Exception:
            pass
    return []

def _already_pending(tid: str) -> bool:
    try:
        return any((x.get("ticket_id") == tid) for x in _get_pending_safe())
    except Exception:
        return False

def _auth_headers() -> Dict[str, str]:
    h = {"Accept": "application/json"}
    if API_TOKEN:
        h["x-api-key"] = API_TOKEN
    return h

async def _post_alerts_ingest(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    שולח ל-/alerts/ingest. תואם לדרישות הולידציה בצד השרת:
    - symbol (UPPER)
    - side (BUY/SELL)
    - qty > 0
    - leverage > 0
    הערה: גם אם require_approval=True, עדיין יש הולידציה על qty/leverage.
    """
    if not ALERTS_INGEST_URL or not PUBLIC_HOST:
        raise RuntimeError("ALERTS_INGEST_URL/PUBLIC_HOST not configured")

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as cli:
        r = await cli.post(ALERTS_INGEST_URL, json=payload, headers=_auth_headers())
        # במידה וה-alerts מחזירים 401 עם הודעות מפורטות — נרצה אותן בלוג
        try:
            data = r.json()
        except Exception:
            data = {"status": r.status_code, "text": r.text}
        if r.status_code >= 400:
            raise RuntimeError(f"alerts_ingest_http_{r.status_code}: {data}")
        return data

def _build_ingest_payload(obj: Dict[str, Any]) -> Dict[str, Any]:
    """
    ממפה פורמט הקובץ המקומי לפורמט /alerts/ingest.
    משלימים qty/leverage מה-ENV כדי לעבור הולידציה.
    """
    symbol = str(obj.get("symbol","")).upper()
    side = str(obj.get("side","")).upper()
    # אם לא קיימים qty/leverage במקור – נשתמש בברירות מחדל
    qty = float(obj.get("qty") or DEFAULT_QTY)
    leverage = int(obj.get("leverage") or DEFAULT_LEVERAGE)
    require_approval = bool(obj.get("require_approval", True))

    # ערכים אינפורמטיביים
    reason = obj.get("reason","")
    score = float(obj.get("score", 0.0))
    expiry_ts = obj.get("expiry_ts")  # אם אין — לא חייבים

    # ניתן להרחיב: tp/sl אם קיימים במקור
    payload: Dict[str, Any] = {
        "trade_id": _ticket_id_for(obj),
        "symbol": symbol,
        "market": str(obj.get("market","futures")).lower(),
        "side": side,  # BUY/SELL
        "qty": qty,
        "leverage": leverage,
        "score": score,
        "reason": reason,
        "require_approval": require_approval,
        "timeframe": obj.get("timeframe","15m"),
    }

    # מיפויים רלוונטיים אם קיימים (לא חובה):
    for k_src, k_dst in [
        ("tp1","tp1"),("tp2","tp2"),("tp3","tp3"),
        ("sl","sl"),
        ("prob_overall_pct","prob_overall_pct"),
        ("prob_tp1_pct","prob_tp1_pct"),
        ("prob_tp2_pct","prob_tp2_pct"),
        ("prob_tp3_pct","prob_tp3_pct"),
        ("eta_open_min","eta_open_min"),
        ("eta_tp1_min","eta_tp1_min"),
        ("eta_tp2_min","eta_tp2_min"),
        ("eta_tp3_min","eta_tp3_min"),
        ("expiry_ts","expiry_ts"),
    ]:
        if obj.get(k_src) is not None:
            payload[k_dst] = obj.get(k_src)

    # guard מינימלי
    if not symbol or side not in ("BUY","SELL"):
        raise ValueError("bad symbol/side in ingest payload")
    if qty <= 0 or leverage <= 0:
        raise ValueError("qty/leverage must be > 0 for alerts/ingest")
    return payload

def _create_ticket_fallback(obj: Dict[str, Any]) -> Optional[str]:
    """
    במידה וה-/alerts/ingest לא זמין/נכשל — נשמור ב-ConfirmStore (כמו קודם).
    """
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
        return ConfirmStore.create(payload) or tid  # type: ignore
    except Exception as e:
        logger.error("ConfirmStore.create failed: %s", e)
        return None

async def _dispatch_signal(obj: Dict[str, Any]) -> Optional[str]:
    """
    ניסיון עיקרי: POST ל-/alerts/ingest (ישלח לטלגרם עם כפתורי אישור/דחייה).
    נפילה אחורה: ConfirmStore.create (ההתנהגות הישנה).
    """
    tid = _ticket_id_for(obj)
    if _already_pending(tid):
        return None

    # אם אין host/URL – לא ננסה רשת
    can_network = bool(PUBLIC_HOST and ALERTS_INGEST_URL)
    if can_network:
        try:
            payload = _build_ingest_payload(obj)
            resp = await _post_alerts_ingest(payload)
            logger.info("alerts/ingest ok: %s", resp)
            return tid
        except Exception as e:
            logger.warning("alerts/ingest failed (%s) — falling back to ConfirmStore", e)

    # fallback מקומי
    return _create_ticket_fallback(obj)

async def _tick_once() -> Dict[str, Any]:
    global TICK_COUNT, LAST_TICK_TS, LAST_CREATED, LAST_PENDING, LAST_ERROR
    created: List[str] = []
    LAST_ERROR = None
    try:
        for obj in _load_ingests():
            tid = await _dispatch_signal(obj)  # ← שינוי לוגי מרכזי
            if tid:
                created.append(tid)
        pend = _get_pending_safe()
        TICK_COUNT += 1
        LAST_TICK_TS = int(time.time())
        LAST_CREATED = created
        LAST_PENDING = len(pend)
        return {"ok": True, "created": created, "pending_count": len(pend)}
    except Exception as e:
        LAST_ERROR = str(e)
        logger.error("tick error: %s", e)
        return {"ok": False, "error": str(e), "created": created}

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
        items = _get_pending_safe()
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
        res = ConfirmStore.decide(req.ticket_id, approved=(act=="APPROVE"))  # type: ignore
        return {"ok": True, "result": res}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"decision failed: {e}")

@router.get("/ops/manager/health")
async def ops_manager_health():
    return {
        "ok": True,
        "enabled": MANAGER_ENABLE,
        "interval_sec": MANAGER_INTERVAL_SEC,
        "ingest_dir": str(INGEST_DIR),
        "last_tick_ts": LAST_TICK_TS,
        "tick_count": TICK_COUNT,
        "created_last": LAST_CREATED,
        "pending_count": LAST_PENDING,
        **({"errors_last": LAST_ERROR} if LAST_ERROR else {}),
        "alerts_ingest_url": ALERTS_INGEST_URL or None,
        "public_host": PUBLIC_HOST or None,
    }

# ---- Background worker (optional) ----
async def _manager_loop():
    logger.info("manager_loop start: enable=%s interval=%ss ingest_dir=%s alerts_ingest=%s",
                MANAGER_ENABLE, MANAGER_INTERVAL_SEC, INGEST_DIR, ALERTS_INGEST_URL or "DISABLED")
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

# ---- Standalone runner ----
def main() -> None:
    if not MANAGER_ENABLE:
        print("MANAGER_ENABLE=0 — exiting.")
        return
    try:
        asyncio.run(_manager_loop())
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()




