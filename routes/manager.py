# routes/manager.py
from __future__ import annotations
import os, json, time, hashlib, asyncio, logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, HTTPException, Header, Body
from pydantic import BaseModel

from utils.anti_replay import verify_request
from utils.telegram_notifier import TelegramNotifier, send_trade_approval  # type: ignore

logger = logging.getLogger("algogpt.manager")
router = APIRouter(tags=["manager"])

BASE_DIR   = Path(os.getenv("BASE_DIR", "/app"))
INGEST_DIR = Path(os.getenv("INGEST_DIR", str(BASE_DIR / "static" / "cache")))
MANAGER_ENABLE       = os.getenv("MANAGER_ENABLE", "1").lower() in ("1","true","yes","on")
MANAGER_INTERVAL_SEC = int(os.getenv("MANAGER_INTERVAL_SEC", "10"))
CONFIRMSTORE_ENABLE  = os.getenv("CONFIRMSTORE_ENABLE", "1").lower() in ("1","true","yes","on")

PUBLIC_HOST = (os.getenv("PUBLIC_HOST", "") or os.getenv("WEBHOOK_HOST", "")).rstrip("/")
ALERTS_INGEST_URL = os.getenv("ALERTS_INGEST_URL", f"{PUBLIC_HOST}/alerts/ingest").strip()
API_TOKEN = os.getenv("API_TOKEN", os.getenv("PRIMARY_API_TOKEN", "")).strip()
API_BEARER_TOKEN = (os.getenv("API_BEARER_TOKEN") or os.getenv("API_TOKEN") or "").strip()

DEFAULT_QTY = float(os.getenv("DEFAULT_QTY", "0.001"))
DEFAULT_LEVERAGE = int(os.getenv("DEFAULT_LEVERAGE", "5"))
HTTP_TIMEOUT = float(os.getenv("MANAGER_HTTP_TIMEOUT", "10.0"))

# ----- State Machine (אופציונלי) -----
try:
    from utils.open_trade_manager_state import TradePlan, TradeStateManager  # type: ignore
    _STATE_MACHINE_AVAILABLE = True
except Exception as _e:
    TradePlan = None      # type: ignore
    TradeStateManager = None  # type: ignore
    _STATE_MACHINE_AVAILABLE = False
    logger.info("StateMachine not available: %s", _e)

# ConfirmStore (respect CONFIRMSTORE_ENABLE)
try:
    if not CONFIRMSTORE_ENABLE:
        raise RuntimeError("ConfirmStore disabled by env")
    from utils.trade_executor import ConfirmStore  # type: ignore
except Exception as e:
    logger.error("ConfirmStore unavailable (%s). Fallback disabled=%s", e, not CONFIRMSTORE_ENABLE)
    class _NoConfirm:
        @classmethod
        def pending(cls) -> List[Dict[str, Any]]: return []
        @classmethod
        def create(cls, payload: Dict[str, Any]) -> str: raise RuntimeError("ConfirmStore disabled")
        @classmethod
        def decide(cls, ticket_id: str, approved: bool) -> Dict[str, Any]:
            raise RuntimeError("ConfirmStore disabled")
        @classmethod
        def flush_all(cls) -> None: return None
    ConfirmStore = _NoConfirm  # type: ignore

TICK_COUNT: int = 0
LAST_TICK_TS: int = 0
LAST_CREATED: List[str] = []
LAST_PENDING: int = 0
LAST_ERROR: Optional[str] = None

# --- Entry-score gate (לא חוסם, רק סימון ללוג/טלגרם/ingest) ---
def _entry_score_block_info(obj: Dict[str, Any]) -> Dict[str, float | bool | str]:
    """
    מחשב האם האיתות "חסום" לפי ENTRY_SCORE_MIN. לא חוסם בפועל — רק מחזיר שדות סימון.
    """
    try:
        min_req = float(os.getenv("ENTRY_SCORE_MIN", "0") or 0)
    except Exception:
        min_req = 0.0
    # אם לא נשלח score, נתמוך ב-None -> נחשב כ-0 לצורך הצגה פשוטה
    try:
        raw_score = obj.get("score", None)
        score = float(raw_score) if raw_score is not None else 0.0
    except Exception:
        score = 0.0

    blocked = (min_req > 0 and score < min_req)
    if blocked:
        badge = "⚠️ BLOCKED_BY_ENTRY_SCORE"
        line  = f"⚠️ blocked: score {score:.2f} < min {min_req:.2f}"
        severity = "warn"
    else:
        badge = "✅ ENTRY SCORE OK"
        # אם min_req==0, נציג “OK” פשוט
        if min_req > 0:
            line = f"✅ entry score OK: {score:.2f} ≥ min {min_req:.2f}"
        else:
            line = f"✅ entry score: {score:.2f}"
        severity = "ok"

    return {
        "blocked": bool(blocked),
        "score": float(score),
        "min_req": float(min_req),
        "badge": badge,
        "status_line": line,
        "severity": severity,
    }

# ========= /manager/open — נקודת כניסה ל-State Machine =========
class TradeOpenRequest(BaseModel):
    symbol: str
    side: str  # BUY | SELL
    qty: float
    entry_price: Optional[float] = None
    sl_price: Optional[float] = None
    tp_price: Optional[float] = None
    leverage: int = 10
    position_side: str = "BOTH"
    time_stop_sec: Optional[int] = None
    meta: Optional[Dict[str, Any]] = None

@router.post("/manager/open")
async def manager_open(req: TradeOpenRequest) -> Dict[str, Any]:
    if not _STATE_MACHINE_AVAILABLE:
        raise HTTPException(status_code=501, detail="StateMachine not available (utils.open_trade_manager_state.py missing)")
    try:
        plan = TradePlan(  # type: ignore[call-arg]
            symbol=req.symbol.upper(),
            side=req.side.upper(),
            qty=float(req.qty),
            entry_price=req.entry_price,
            sl_price=req.sl_price,
            tp_price=req.tp_price,
            leverage=int(req.leverage),
            position_side=req.position_side.upper(),
            time_stop_sec=req.time_stop_sec,
            meta=req.meta or {},
        )
        mgr = TradeStateManager(plan)  # type: ignore[call-arg]
        res = await asyncio.get_running_loop().run_in_executor(None, mgr.run_once)
        if not isinstance(res, dict):
            res = {"ok": True, "result": res}
        res.setdefault("state_available", True)
        return res
    except Exception as e:
        logger.exception("manager_open failed")
        raise HTTPException(status_code=500, detail={"ok": False, "error": str(e)})

# ========= חלק האינגסט והאישורים =========

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
    try:
        res = ConfirmStore.pending()  # type: ignore
        return [x for x in res if isinstance(x, dict)]
    except Exception:
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
    if not ALERTS_INGEST_URL or not PUBLIC_HOST:
        raise RuntimeError("ALERTS_INGEST_URL/PUBLIC_HOST not configured")
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as cli:
        r = await cli.post(ALERTS_INGEST_URL, json=payload, headers=_auth_headers())
        try:
            data = r.json()
        except Exception:
            data = {"status": r.status_code, "text": r.text}
        if r.status_code >= 400:
            raise RuntimeError(f"alerts_ingest_http_{r.status_code}: {data}")
        return data

def _build_ingest_payload(obj: Dict[str, Any]) -> Dict[str, Any]:
    symbol = str(obj.get("symbol","")).upper()
    side = str(obj.get("side","")).upper()
    qty = float(obj.get("qty") or DEFAULT_QTY)
    leverage = int(obj.get("leverage") or DEFAULT_LEVERAGE)
    require_approval = bool(obj.get("require_approval", True))
    reason = obj.get("reason","")
    # קריאת score “רכה”
    try:
        score = float(obj.get("score", 0.0) or 0.0)
    except Exception:
        score = 0.0

    # סימון Entry Score (לא חוסם, רק מידע)
    es = _entry_score_block_info(obj)

    payload: Dict[str, Any] = {
        "ticket_id": _ticket_id_for(obj),
        "symbol": symbol,
        "market": str(obj.get("market","futures")).lower(),
        "side": side,
        "qty": qty,
        "leverage": leverage,
        "score": score,
        "reason": reason,
        "require_approval": require_approval,
        "timeframe": obj.get("timeframe","15m"),
        "tp1": obj.get("tp1"),
        "tp2": obj.get("tp2"),
        "tp3": obj.get("tp3"),
        "sl": obj.get("sl"),

        # >>> הרחבה ל-/alerts/ingest <<<
        "blocked_by_entry_score": bool(es["blocked"]),
        "entry_score": float(es["score"]),
        "entry_score_min": float(es["min_req"]),
    }
    for k in ["prob_overall_pct","prob_tp1_pct","prob_tp2_pct","prob_tp3_pct",
              "eta_open_min","eta_tp1_min","eta_tp2_min","eta_tp3_min","expiry_ts","tp_splits","position_side","note",
              "entry_price","price","approve_url","reject_url","ticket_url","budget_usd","ttl_sec"]:
        if obj.get(k) is not None:
            payload[k] = obj.get(k)

    if not symbol or side not in ("BUY","SELL"):
        raise ValueError("bad symbol/side in ingest payload")
    if qty <= 0 or leverage <= 0:
        raise ValueError("qty/leverage must be > 0 for alerts/ingest")
    return payload

def _create_ticket_fallback(obj: Dict[str, Any]) -> Optional[str]:
    if not CONFIRMSTORE_ENABLE:
        return None
    if not obj.get("symbol") or not obj.get("side"):
        return None
    payload = {
        "ticket_id": _ticket_id_for(obj),
        "source": obj.get("source","ingest"),
        "symbol": obj.get("symbol"),
        "market": obj.get("market","futures"),
        "timeframe": obj.get("timeframe","15m"),
        "side": obj.get("side"),
        "score": float(obj.get("score", 0.0)) if obj.get("score") is not None else None,
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

async def _notify_telegram_approval_from_obj(obj: Dict[str, Any], ticket_id: str) -> None:
    # סימון "חסום לפי ציון" (לא עוצר פעולה, רק מידע)
    es = _entry_score_block_info(obj)

    symbol = str(obj.get("symbol","")).upper()
    side   = str(obj.get("side","")).upper()
    leverage = obj.get("leverage") or DEFAULT_LEVERAGE
    tp_legs = []
    for i in (1,2,3):
        v = obj.get(f"tp{i}")
        if v is None:
            continue
        try:
            tp_legs.append({"stopPrice": float(v), "split": obj.get("tp_splits", [0.4,0.35,0.25])[i-1] if isinstance(obj.get("tp_splits"), list) else None})
        except Exception:
            pass
    sl_px = obj.get("sl")
    sl_obj = {"stopPrice": float(sl_px)} if sl_px is not None else {}

    probs = {
        "overall": obj.get("prob_overall_pct"),
        "tp1": obj.get("prob_tp1_pct"),
        "tp2": obj.get("prob_tp2_pct"),
        "tp3": obj.get("prob_tp3_pct"),
    }
    eta = {
        "entry_sec": (obj.get("eta_open_min") or 0) * 60 if obj.get("eta_open_min") is not None else None,
        "tp1_sec": (obj.get("eta_tp1_min") or 0) * 60 if obj.get("eta_tp1_min") is not None else None,
        "tp2_sec": (obj.get("eta_tp2_min") or 0) * 60 if obj.get("eta_tp2_min") is not None else None,
        "tp3_sec": (obj.get("eta_tp3_min") or 0) * 60 if obj.get("eta_tp3_min") is not None else None,
    }

    base_why = (obj.get("reason") or "")
    # נדביק את שורת הסטטוס ל־why כדי שיופיע בוודאות בהודעה
    if es["status_line"]:
        why = f"{es['status_line']} | {base_why}".strip(" |")
    else:
        why = base_why

    plan: Dict[str, Any] = {
        "symbol": symbol,
        "side": side,
        "leverage": leverage,
        "order_type": "MARKET",
        "entry_price": obj.get("entry_price") or obj.get("price"),
        "sl": sl_obj,
        "tp": tp_legs,
        "timeframe": obj.get("timeframe","15m"),
        "why": why,
        "score": float(obj.get("score",0.0) or 0.0),

        # >>> שדות סימון חדשים לטלגרם/UI <<<
        "blocked_by_entry_score": bool(es["blocked"]),
        "entry_score": float(es["score"]),
        "entry_score_min": float(es["min_req"]),
        "badges": [str(es["badge"])],
        "entry_score_status_line": str(es["status_line"]),
        "severity": str(es["severity"]),

        "probs": probs,
        "eta": eta,
        "trade_kind": obj.get("market","futures"),
        "budget_usd": obj.get("budget_usd"),
        "approve_url": obj.get("approve_url"),
        "reject_url": obj.get("reject_url"),
        "ticket_url": obj.get("ticket_url"),
        "require_approval": obj.get("require_approval", True),
        "ttl_sec": int(obj.get("ttl_sec") or 600),
    }
    try:
        await send_trade_approval(ticket_id, plan, chat_id=None)
    except Exception as e:
        logger.warning("telegram approval notify failed: %s", e)

async def _dispatch_signal(obj: Dict[str, Any]) -> Optional[str]:
    tid = _ticket_id_for(obj)
    if _already_pending(tid):
        return None
    can_network = bool(PUBLIC_HOST and ALERTS_INGEST_URL)
    if can_network:
        try:
            payload = _build_ingest_payload(obj)
            resp = await _post_alerts_ingest(payload)
            logger.info("alerts/ingest ok: %s", resp)
            await _notify_telegram_approval_from_obj(obj, ticket_id=payload["ticket_id"])
            return tid
        except Exception as e:
            logger.warning("alerts/ingest failed (%s) — fallback ConfirmStore", e)

    tid_fb = _create_ticket_fallback(obj)
    if tid_fb:
        await _notify_telegram_approval_from_obj(obj, ticket_id=tid_fb)
    return tid_fb

async def _tick_once() -> Dict[str, Any]:
    global TICK_COUNT, LAST_TICK_TS, LAST_CREATED, LAST_PENDING, LAST_ERROR
    created: List[str] = []
    LAST_ERROR = None
    try:
        for obj in _load_ingests():
            tid = await _dispatch_signal(obj)
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

# === Public Manager Endpoints ===

@router.post("/ops/manager/tick")
async def ops_manager_tick():
    """Single tick to ingest files -> tickets -> telegram."""
    return await _tick_once()

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
        "state_machine": _STATE_MACHINE_AVAILABLE,
    }

# === Tickets status / actions ===

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

class UpdateTicketReq(BaseModel):
    ticket_id: str
    action: str  # APPROVE | REJECT

@router.post("/alerts/trades/update")
async def alerts_trades_update(
    req: UpdateTicketReq,
    x_timestamp: Optional[str] = Header(None, alias="X-Timestamp"),
    x_nonce: Optional[str]   = Header(None, alias="X-Nonce"),
    x_signature: Optional[str]= Header(None, alias="X-Signature"),
):
    ok, why = verify_request(
        ts_header=x_timestamp,
        nonce_header=x_nonce,
        signature_header=x_signature,
        route="/alerts/trades/update",
        body=req.dict(),
        require_signature=(os.getenv("ANTI_REPLAY_REQUIRE_SIGNATURE", "0").lower() in ("1","true","yes","on")),
    )
    if not ok:
        raise HTTPException(status_code=400, detail=f"anti_replay_failed: {why}")

    act = req.action.upper().strip()
    if act not in ("APPROVE","REJECT"):
        raise HTTPException(status_code=400, detail="action must be APPROVE or REJECT")
    try:
        res = ConfirmStore.decide(req.ticket_id, approved=(act=="APPROVE"))  # type: ignore
        return {"ok": True, "result": res}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"decision failed: {e}")

# === One-shot manager hook (LITE) ===

class ManageOnceReq(BaseModel):
    symbol: Optional[str] = None
    offset_bps: Optional[int] = None
    pcts: Optional[List[float]] = None
    splits: Optional[List[float]] = None
    atr_mult: Optional[float] = None

def _bearer_ok(auth_header: Optional[str]) -> bool:
    if not API_BEARER_TOKEN:
        return True  # ללא טוקן — לא חוסמים (לוקאלי)
    if not (auth_header and auth_header.startswith("Bearer ")):
        return False
    token = auth_header.split(" ", 1)[1].strip()
    return token == API_BEARER_TOKEN

@router.post("/manage-once-lite")
async def manage_once_lite(
    req: ManageOnceReq = Body(...),
    authorization: Optional[str] = Header(None, alias="Authorization"),
) -> Dict[str, Any]:
    """
    Lightweight endpoint invoked internally to perform a single management cycle for a symbol.
    Tries to call a concrete manager if available; otherwise returns ok=True so the caller won't back off.
    נפרד מה־/manage-once המרכזי של main.py כדי למנוע כפילויות.
    """
    if not _bearer_ok(authorization):
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        from routes.position_ops import manage_once as real_manage_once  # type: ignore
        payload: Dict[str, Any] = {k: v for k, v in req.dict().items() if v is not None}
        res = await real_manage_once(payload)  # type: ignore
        return {"ok": True, "delegated": True, "result": res}
    except Exception:
        pass
    try:
        from utils.position_manager import manage_once as pm_manage_once  # type: ignore
        res = await pm_manage_once(**{k: v for k, v in req.dict().items() if v is not None})  # type: ignore
        return {"ok": True, "delegated": True, "result": res}
    except Exception:
        return {"ok": True, "delegated": False, "skipped": True, "reason": "manager_not_available"}

# === Background loop (optional) ===

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



