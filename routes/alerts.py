# routes/alerts.py
from __future__ import annotations
import os, hmac, hashlib, time, json, logging
from typing import Any, Dict, Optional, Tuple
from contextlib import suppress

from fastapi import APIRouter, Body, Header, Request, HTTPException
from pydantic import BaseModel

logger = logging.getLogger("algogpt.alerts")
router = APIRouter(tags=["alerts"])

# ===== Auth (רך) =====
API_TOKEN = (os.getenv("API_TOKEN") or os.getenv("PRIMARY_API_TOKEN") or "").strip()

def _api_key_ok(hdr: Optional[str]) -> bool:
    if not API_TOKEN:
        return True
    return bool(hdr and hdr.strip() == API_TOKEN)

# ===== Optional HMAC (ingest) =====
INGEST_SEC = (os.getenv("ALERTS_INGEST_HMAC_SECRET") or "").strip()
INGEST_HEX = (os.getenv("ALERTS_INGEST_HMAC_KEY_IS_HEX", "0").lower() in ("1","true","yes","on"))
DEBUG_HMAC  = (os.getenv("DEBUG_ALERTS_HMAC_CHECK","0").lower() in ("1","true","yes","on"))

def _hmac_check(route: str, body_bytes: bytes, ts: Optional[str], nonce: Optional[str], sig: Optional[str]) -> Tuple[bool,str]:
    if not INGEST_SEC:
        return True, "no_secret"
    if not (ts and nonce and sig):
        return False, "missing_headers"
    msg = f"{route}|{ts}|{nonce}|".encode("utf-8") + (body_bytes or b"")
    key = bytes.fromhex(INGEST_SEC) if INGEST_HEX and len(INGEST_SEC) % 2 == 0 else INGEST_SEC.encode("utf-8")
    calc = hmac.new(key, msg, hashlib.sha256).hexdigest()
    return (calc == sig, "bad_sig" if calc != sig else "ok")

# ===== Optional ConfirmStore =====
_HAS_CONFIRM = False
with suppress(Exception):
    # נסה קודם מ-main (אם הוגדר שם)
    from main import ConfirmStore as _ConfirmStoreMain  # type: ignore
    ConfirmStore = _ConfirmStoreMain  # type: ignore
    _HAS_CONFIRM = True
if not _HAS_CONFIRM:
    # Fallback קטן בזיכרון — לא חובה.
    class ConfirmStore:  # type: ignore
        _items: Dict[str, Dict[str, Any]] = {}
        @classmethod
        def create(cls, req: Dict[str, Any]) -> None:
            cls._items[str(req.get("ticket_id","TKT"))] = {"req": dict(req), "ts": time.time()}
    _HAS_CONFIRM = True

# ===== Telegram send helper (רך) =====
async def _tg_send_plan(plan: Dict[str, Any]) -> None:
    with suppress(Exception):
        from utils.alerts import send_telegram_message  # type: ignore
        sym = plan.get("symbol","")
        side = plan.get("side","")
        lev = plan.get("leverage","")
        qty = plan.get("qty","")
        lines = [
            "🔔 <b>Trade Ingest</b>",
            f"• {sym} {side} qty=<code>{qty}</code> lev=<code>{lev}</code>",
        ]
        if plan.get("budget_usd"):
            lines.append(f"• Budget: <code>${plan['budget_usd']}</code>")
        if plan.get("score") is not None:
            lines.append(f"• Score: <code>{plan['score']}</code>")
        if plan.get("why"):
            lines.append(f"• Note: {plan['why']}")
        await send_telegram_message("\n".join(lines), parse_mode="HTML", disable_preview=True)

# ===== Binance helpers (רק למחיר) =====
def _get_client_soft():
    try:
        from binance.client import Client  # type: ignore
    except Exception as e:
        return None, f"binance_import_failed: {e}"
    ak = os.getenv("BINANCE_API_KEY","").strip()
    sk = os.getenv("BINANCE_API_SECRET","").strip()
    if not ak or not sk:
        return None, "binance_keys_missing"
    try:
        return Client(ak, sk), None
    except Exception as e:
        return None, f"binance_client_init_failed: {e}"

def _last_price(client, symbol: str) -> float:
    p = client.futures_symbol_ticker(symbol=symbol.upper())
    return float(p["price"])

# ===== Request/Response models =====
class IngestReq(BaseModel):
    # חובה:
    symbol: str
    side: str  # BUY | SELL
    market: str = "futures"
    # אחת מהאפשרויות: qty או budget_usd (+ leverage)
    qty: Optional[float] = None
    budget_usd: Optional[float] = None
    leverage: Optional[int] = None
    # מידע נוסף (לא חובה)
    ticket_id: Optional[str] = None
    timeframe: Optional[str] = "15m"
    score: Optional[float] = 0.0
    reason: Optional[str] = ""
    require_approval: Optional[bool] = True
    tp1: Optional[dict] | Optional[float] = None
    tp2: Optional[dict] | Optional[float] = None
    tp3: Optional[dict] | Optional[float] = None
    sl: Optional[dict] | Optional[float] = None
    note: Optional[str] = None

def _ticket_id_for(req: IngestReq) -> str:
    base = {
        "symbol": req.symbol.upper(),
        "side": req.side.upper(),
        "market": (req.market or "futures").lower(),
        "timeframe": req.timeframe,
        "reason": req.reason or "",
        "score": float(req.score or 0),
    }
    h = hashlib.sha256(json.dumps(base, sort_keys=True).encode()).hexdigest()[:16]
    return f"TKT-{h}"

def _compute_qty_from_budget(symbol: str, budget_usd: float, leverage: int) -> tuple[float, Optional[str]]:
    cli, err = _get_client_soft()
    if not cli:
        return 0.0, err or "binance_client_error"
    try:
        px = _last_price(cli, symbol)
        if px <= 0:
            return 0.0, "bad_price"
        qty = (float(budget_usd) * float(leverage)) / px
        return float(qty), None
    except Exception as e:
        return 0.0, f"price_fetch_failed: {e}"

# ===== Endpoints =====
@router.post("/alerts/ingest")
async def alerts_ingest(
    req: IngestReq = Body(...),
    request: Request = None,
    x_api_key: Optional[str] = Header(None, alias="x-api-key"),
    x_timestamp: Optional[str] = Header(None, alias="X-Timestamp"),
    x_nonce: Optional[str] = Header(None, alias="X-Nonce"),
    x_signature: Optional[str] = Header(None, alias="X-Signature"),
):
    # API key (רך): אם הוגדר, נדרוש אותו
    if not _api_key_ok(x_api_key):
        return {"ok": False, "error": "unauthorized"}

    # HMAC אופציונלי (לפי גוף המקורי)
    raw_body = b""
    with suppress(Exception):
        raw_body = await request.body() if request else json.dumps(req.dict()).encode("utf-8")
    if DEBUG_HMAC and INGEST_SEC:
        ok, why = _hmac_check("/alerts/ingest", raw_body, x_timestamp, x_nonce, x_signature)
        if not ok:
            return {"ok": False, "error": f"hmac_{why}"}

    sym = (req.symbol or "").upper().strip()
    side_raw = (req.side or "").upper().strip()
    # תמיכה ב-LONG/SHORT (Futures) וגם ב-BUY/SELL (קלאסי)
    if side_raw in ("LONG", "BUY"):
        side = "BUY"
    elif side_raw in ("SHORT", "SELL"):
        side = "SELL"
    else:
        return {"ok": False, "error": "bad_symbol_or_side"}
    
    if sym == "":
        return {"ok": False, "error": "bad_symbol"}

    qty = req.qty
    if qty is None:
        bud = float(req.budget_usd or 0.0)
        lev = int(req.leverage or int(os.getenv("DEFAULT_LEVERAGE","5")))
        if bud <= 0:
            return {"ok": False, "error": "qty_or_budget_required"}
        qty, qerr = _compute_qty_from_budget(sym, bud, lev)
        if qerr:
            return {"ok": False, "error": qerr}
        req.qty = qty
        req.leverage = lev

    plan: Dict[str, Any] = {
        "symbol": sym,
        "side": side,
        "market": (req.market or "futures").lower(),
        "timeframe": req.timeframe,
        "leverage": int(req.leverage or int(os.getenv("DEFAULT_LEVERAGE","5"))),
        "qty": float(req.qty or 0),
        "score": float(req.score or 0),
        "why": req.reason or "",
        "tp": [x for x in (req.tp1, req.tp2, req.tp3) if isinstance(x, dict)],
        "sl": ({"stopPrice": float(req.sl)} if isinstance(req.sl,(int,float)) and float(req.sl)>0 else (req.sl if isinstance(req.sl,dict) else {})),
        "budget_usd": float(req.budget_usd or 0),
        "order_type": "MARKET",
        "require_approval": bool(req.require_approval if req.require_approval is not None else True),
    }

    tid = req.ticket_id or _ticket_id_for(req)
    plan["ticket_id"] = tid

    if _HAS_CONFIRM:
        with suppress(Exception):
            ConfirmStore.create({  # type: ignore
                "ticket_id": tid, "source": "ingest",
                "symbol": sym, "market": plan["market"], "timeframe": req.timeframe,
                "side": side, "score": float(req.score or 0), "reason": req.reason or "",
                "require_approval": bool(plan["require_approval"]), "ts": int(time.time()),
            })

    await _tg_send_plan(plan)  # רך: אם נכשל לא מפיל

    return {"ok": True, "ticket_id": tid, "symbol": sym, "qty": float(req.qty or 0), "leverage": int(plan["leverage"])}

@router.get("/alerts/ingest")
async def alerts_ingest_health():
    return {"ok": True, "ingest": "ready"}





























