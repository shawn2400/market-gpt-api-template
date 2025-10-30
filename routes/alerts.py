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

# ===== Telegram send helper (משופר עם כפתורים ופרטים מלאים) =====
async def _tg_send_plan(plan: Dict[str, Any]) -> None:
    with suppress(Exception):
        from utils.alerts import send_telegram_message  # type: ignore
        
        sym = plan.get("symbol", "")
        side = plan.get("side", "")
        lev = plan.get("leverage", "")
        qty = plan.get("qty", "")
        ticket_id = plan.get("ticket_id", "")
        
        # חלץ TP/SL מהנתונים
        tp_list = plan.get("tp", [])
        sl_dict = plan.get("sl", {})
        
        # בנה הודעה עשירה בפרטים
        emoji_side = "🟢" if side == "BUY" else "🔴"
        lines = [
            f"{emoji_side} <b>NEW TRADE PROPOSAL</b>",
            f"",
            f"💎 <b>{sym}</b>",
            f"📊 Direction: <b>{side}</b> (Leverage: x{lev})",
            f"💰 Quantity: <code>{qty:.6f}</code>",
        ]
        
        if plan.get("budget_usd"):
            lines.append(f"💵 Budget: <code>${plan['budget_usd']:.2f}</code>")
        
        # הוסף Entry/SL/TP אם קיימים
        entry = plan.get("entry")
        if entry:
            lines.append(f"🎯 Entry: <code>{entry:.2f}</code>")
        
        if sl_dict and sl_dict.get("stopPrice"):
            lines.append(f"🛑 Stop Loss: <code>{sl_dict['stopPrice']:.2f}</code>")
        
        if tp_list:
            lines.append(f"🎯 Take Profit:")
            for i, tp in enumerate(tp_list[:3], 1):
                if isinstance(tp, dict) and tp.get("price"):
                    lines.append(f"   TP{i}: <code>{tp['price']:.2f}</code>")
        
        # חישובי RR ו-Success
        if plan.get("score"):
            lines.append(f"⭐ Quality Score: <code>{plan['score']:.1f}/10</code>")
        
        # Success % אם קיים
        success_pct = plan.get("success_pct")
        if success_pct:
            lines.append(f"📈 Success Probability: <code>{success_pct:.1f}%</code>")
        
        # סיבה/אסטרטגיה
        if plan.get("why"):
            lines.append(f"")
            lines.append(f"📝 Strategy: {plan['why'][:150]}")
        
        lines.append(f"")
        lines.append(f"⏱️ Timeframe: <code>{plan.get('timeframe', '15m')}</code>")
        lines.append(f"")
        lines.append(f"<i>🤖 Auto-analyzed by AI Scanner</i>")
        
        # כפתורים ירוקים/אדומים (פורמט: CONFIRM:ACTION:TICKET_ID)
        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "✅ APPROVE", "callback_data": f"CONFIRM:APPROVE:{ticket_id}"},
                    {"text": "❌ REJECT", "callback_data": f"CONFIRM:REJECT:{ticket_id}"}
                ],
                [
                    {"text": "📊 View Full Details", "callback_data": f"CONFIRM:DETAILS:{ticket_id}"}
                ]
            ]
        }
        
        await send_telegram_message(
            "\n".join(lines), 
            parse_mode="HTML", 
            disable_preview=True,
            reply_markup=keyboard
        )

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
    side: str  # BUY | SELL | LONG | SHORT
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
    entry: Optional[float] = None
    success_pct: Optional[float] = None
    current_price: Optional[float] = None
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

def _to_float(x):
    try:
        return float(x) if x is not None else None
    except:
        return None

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

    # המר TP/SL מ-float ל-dict אם צריך (תמיכה ב-Worker format)
    def _to_tp_dict(val, idx):
        if isinstance(val, dict):
            return val
        elif isinstance(val, (int, float)) and float(val) > 0:
            return {"price": float(val), "pct": 25.0 if idx == 1 else (33.0 if idx == 2 else 100.0)}
        return None
    
    tp_dicts = [_to_tp_dict(x, i) for i, x in enumerate([req.tp1, req.tp2, req.tp3], 1)]
    tp_list = [x for x in tp_dicts if x is not None]
    
    sl_data = req.sl
    if isinstance(sl_data, (int, float)) and float(sl_data) > 0:
        sl_dict = {"stopPrice": float(sl_data)}
    elif isinstance(sl_data, dict):
        sl_dict = sl_data
    else:
        sl_dict = {}
    
    # Smart portfolio management
    score = float(req.score or 0)
    base_lev = int(req.leverage or int(os.getenv("DEFAULT_LEVERAGE","5")))
    
    # Apply score-based leverage and budget allocation
    try:
        from utils.portfolio_manager import calculate_score_based_leverage, calculate_trade_budget
        
        smart_lev = calculate_score_based_leverage(base_lev, score, max_lev=20)
        budget_result = calculate_trade_budget(score)
        
        if budget_result.get("ok") and not req.budget_usd:
            smart_budget = budget_result["budget_usdt"]
        else:
            smart_budget = float(req.budget_usd or 0)
    except Exception:
        smart_lev = base_lev
        smart_budget = float(req.budget_usd or 0)
    
    plan: Dict[str, Any] = {
        "symbol": sym,
        "side": side,
        "market": (req.market or "futures").lower(),
        "timeframe": req.timeframe,
        "leverage": smart_lev,  # Score-based leverage
        "qty": float(req.qty or 0),
        "score": score,
        "why": req.reason or "",
        "tp": tp_list,
        "sl": sl_dict,
        "budget_usd": smart_budget,  # Smart budget allocation
        "order_type": "MARKET",
        "require_approval": bool(req.require_approval if req.require_approval is not None else True),
        "entry": _to_float(req.entry),
        "success_pct": _to_float(req.success_pct) if req.success_pct else score,
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





























