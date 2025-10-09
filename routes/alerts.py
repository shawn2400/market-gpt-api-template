# routes/alerts.py
from __future__ import annotations
import os, hmac, hashlib, time, json, logging
from typing import Any, Dict, Optional
from contextlib import suppress

from fastapi import APIRouter, Body, Header
from pydantic import BaseModel

logger = logging.getLogger("algogpt.alerts")
router = APIRouter(tags=["alerts"])

# ===== Auth =====
API_TOKEN = (os.getenv("API_TOKEN") or os.getenv("PRIMARY_API_TOKEN") or "").strip()

def _api_key_ok(hdr: Optional[str]) -> bool:
    if not API_TOKEN:
        return True
    return bool(hdr and hdr.strip() == API_TOKEN)

# ===== Optional HMAC (ingest) =====
INGEST_SEC = (os.getenv("ALERTS_INGEST_HMAC_SECRET") or "").strip()
INGEST_HEX = (os.getenv("ALERTS_INGEST_HMAC_KEY_IS_HEX", "0").lower() in ("1","true","yes","on"))
DEBUG_HMAC  = (os.getenv("DEBUG_ALERTS_HMAC_CHECK","0").lower() in ("1","true","yes","on"))

def _hmac_check(route: str, body_bytes: bytes, ts: Optional[str], nonce: Optional[str], sig: Optional[str]) -> tuple[bool,str]:
    if not INGEST_SEC:
        return True, "no_secret"
    if not (ts and nonce and sig):
        return False, "missing_headers"
    msg = f"{route}|{ts}|{nonce}|".encode("utf-8") + body_bytes
    key = bytes.fromhex(INGEST_SEC) if INGEST_HEX and len(INGEST_SEC) % 2 == 0 else INGEST_SEC.encode("utf-8")
    calc = hmac.new(key, msg, hashlib.sha256).hexdigest()
    return (calc == sig, "bad_sig" if calc != sig else "ok")

# ===== Optional ConfirmStore & Telegram =====
with suppress(Exception):
    from utils.trade_executor import ConfirmStore  # type: ignore
    _HAS_CONFIRM = True
with suppress(Exception):
    _HAS_CONFIRM
except NameError:
    _HAS_CONFIRM = False

with suppress(Exception):
    from utils.telegram_notifier import send_trade_approval  # type: ignore

# ===== Binance helpers (רק למחיר ו־filters) =====
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
    tp1: Optional[dict] = None
    tp2: Optional[dict] = None
    tp3: Optional[dict] = None
    sl: Optional[dict] | Optional[float] = None
    note: Optional[str] = None

def _ticket_id_for(req: IngestReq) -> str:
    base = {
        "symbol": req.symbol.upper(),
        "side": req.side.upper(),
        "market": req.market.lower(),
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
        # futures notional = qty * price; margin = notional / leverage
        # לכן qty ≈ (budget_usd * leverage) / price
        qty = (float(budget_usd) * float(leverage)) / px
        return float(qty), None
    except Exception as e:
        return 0.0, f"price_fetch_failed: {e}"

@router.post("/alerts/ingest")
async def alerts_ingest(
    req: IngestReq = Body(...),
    x_api_key: Optional[str] = Header(None, alias="x-api-key"),
    x_timestamp: Optional[str] = Header(None, alias="X-Timestamp"),
    x_nonce: Optional[str] = Header(None, alias="X-Nonce"),
    x_signature: Optional[str] = Header(None, alias="X-Signature"),
    raw_body: bytes = Body(b""),
):
    # API key (רך): אם הוגדר, נדרוש אותו
    if not _api_key_ok(x_api_key):
        return {"ok": False, "error": "unauthorized"}

    # HMAC אופציונלי
    if DEBUG_HMAC and INGEST_SEC:
        ok, why = _hmac_check("/alerts/ingest", raw_body or json.dumps(req.dict()).encode("utf-8"), x_timestamp, x_nonce, x_signature)
        if not ok:
            return {"ok": False, "error": f"hmac_{why}"}

    sym = (req.symbol or "").upper().strip()
    side = (req.side or "").upper().strip()
    if sym == "" or side not in ("BUY","SELL"):
        return {"ok": False, "error": "bad_symbol_or_side"}

    qty = req.qty
    if qty is None:
        # לחשב מכסף + מינוף
        bud = float(req.budget_usd or 0.0)
        lev = int(req.leverage or os.getenv("DEFAULT_LEVERAGE","5"))
        if bud <= 0:
            return {"ok": False, "error": "qty_or_budget_required"}
        qty, qerr = _compute_qty_from_budget(sym, bud, lev)
        if qerr:
            return {"ok": False, "error": qerr}
        req.qty = qty
        req.leverage = lev

    # בנה מזה “תוכנית” לטלגרם
    plan: Dict[str, Any] = {
        "symbol": sym,
        "side": side,
        "market": req.market.lower(),
        "timeframe": req.timeframe,
        "leverage": int(req.leverage or os.getenv("DEFAULT_LEVERAGE","5")),
        "qty": float(req.qty or 0),
        "score": float(req.score or 0),
        "why": req.reason or "",
        "tp": [x for x in (req.tp1, req.tp2, req.tp3) if isinstance(x, dict)],
        "sl": ({"stopPrice": float(req.sl)} if isinstance(req.sl,(int,float)) and float(req.sl)>0 else (req.sl if isinstance(req.sl,dict) else {})),
        "budget_usd": float(req.budget_usd or 0),
        "order_type": "MARKET",
        "require_approval": bool(req.require_approval if req.require_approval is not None else True),
    }

    # צור ticket_id אם חסר
    tid = req.ticket_id or _ticket_id_for(req)
    plan["ticket_id"] = tid

    # ConfirmStore (אם קיים)
    if _HAS_CONFIRM:
        try:
            payload = {
                "ticket_id": tid,
                "source": "ingest",
                "symbol": sym,
                "market": req.market.lower(),
                "timeframe": req.timeframe,
                "side": side,
                "score": float(req.score or 0),
                "reason": req.reason or "",
                "require_approval": bool(plan["require_approval"]),
                "ts": int(time.time()),
            }
            with suppress(Exception):
                ConfirmStore.create(payload)  # type: ignore
        except Exception as e:
            logger.warning("ConfirmStore.create failed: %s", e)

    # שלח הודעת אישור לטלגרם (רך)
    with suppress(Exception):
        await send_trade_approval(tid, plan)  # type: ignore

    return {"ok": True, "ticket_id": tid, "symbol": sym, "qty": float(req.qty or 0), "leverage": int(plan["leverage"])}

# Optional: ping
@router.get("/alerts/ingest")
async def alerts_ingest_health():
    return {"ok": True, "ingest": "ready"}





























