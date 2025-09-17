from __future__ import annotations
import os, time, math, secrets
from typing import List, Optional, Dict, Any, Literal, Tuple
from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from utils.auth import require_api_key

# נסה להביא מחיר חי; אם אין – נשתמש בגיבוי 100_000.0
try:
    from utils.binance_client import get_price as _get_price_live
except Exception:
    _get_price_live = None

router = APIRouter(tags=["trade (legacy)"])

# ---------- Idempotency ----------
_IDEM: Dict[str, float] = {}
_IDEM_TTL_SEC = 15.0

def _idem_check(key: Optional[str], dry_run: bool) -> Optional[JSONResponse]:
    if not key:
        return None
    now = time.time()
    exp = _IDEM.get(key)
    if exp and exp > now:
        ttl = max(0, int(exp - now))
        # שמרנו התנהגות "idem_conflict" כמו שראית
        return JSONResponse(status_code=409, content={"ok": False, "error": "idem_conflict",
                             "result": {"ok": False, "reason": "idem_conflict", "ttl_sec": ttl}})
    # גם ב-dry_run נרשום מפתח כדי למנוע ספאם כפול מיידי
    _IDEM[key] = now + _IDEM_TTL_SEC
    return None

# ---------- מודל קלט ----------
class TradeRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=32)
    side: Literal["BUY", "SELL"]
    leverage: int = Field(1, ge=1, le=125)
    budget_usd: Optional[float] = Field(default=None, ge=0)
    dry_run: bool = True
    confirm_first: bool = False

    entry: Optional[float] = Field(default=None, ge=0)
    tp_targets: Optional[List[float]] = None
    tp_splits: Optional[List[float]] = None

    @field_validator("side", mode="before")
    @classmethod
    def _side_upper(cls, v):
        if isinstance(v, str):
            v = v.strip().upper()
        if v not in ("BUY", "SELL"):
            raise ValueError("side must be BUY or SELL")
        return v

    @field_validator("tp_splits")
    @classmethod
    def _tp_sum_le_one(cls, v):
        if v is not None and sum(v) > 1.0 + 1e-9:
            raise ValueError("tp_splits sum must be <= 1.0")
        return v

# ---------- לוגיקה דינמית SL/TP ----------
def _price(symbol: str) -> float:
    if callable(_get_price_live):
        try:
            p = _get_price_live(symbol)
            if p and p > 0:
                return float(p)
        except Exception:
            pass
    return 100_000.0

def _sign(side: str) -> int:
    return +1 if side == "BUY" else -1

def _round_qty(q: float) -> float:
    # עיגול "אנושי": אל שלושה ספרות אחרי הנקודה (BTC/ETH)
    q = max(q, 0.0)
    return round(q, 3) if q >= 0.001 else (0.001 if q > 0 else 0.0)

def _default_tp_sl(base: float, side: str) -> Tuple[List[float], List[Dict[str, Any]]]:
    """
    מחזיר: (tp_targets, sl_orders)
    TP: +1.8% / +3.0% / +5.0% לביי (היפוך לסל)
    SL:  -0.25% לביי (היפוך לסל)
    """
    s = _sign(side)
    tps = [base * (1 + s * 0.018), base * (1 + s * 0.030), base * (1 + s * 0.050)]
    sl  = base * (1 - s * 0.0025)
    return [float(x) for x in tps], [{"type": "STOP_MARKET", "stopPrice": float(sl)}]

def _build_result(req: TradeRequest) -> Dict[str, Any]:
    symbol = req.symbol.upper()
    side   = req.side
    base   = _price(symbol)
    # כמות משוערת
    notional = float(req.budget_usd or 0.0) * max(1, int(req.leverage))
    qty = _round_qty(notional / base) if base > 0 else 0.0

    # TP/SL דיפולט
    if req.tp_targets:
        tp_targets = [float(x) for x in req.tp_targets]
    else:
        tp_targets, sl_orders = _default_tp_sl(base, side)

    if not req.tp_splits:
        splits = [1/3, 1/3, 1 - 2/3] if len(tp_targets) >= 3 else [1.0] * len(tp_targets)
    else:
        splits = req.tp_splits

    tp_orders = []
    for i, tgt in enumerate(tp_targets):
        part = splits[i] if i < len(splits) else 0.0
        q_i = _round_qty(qty * part)
        if q_i > 0:
            tp_orders.append({"type": "TAKE_PROFIT_MARKET", "stopPrice": float(tgt), "qty": q_i})

    if 'sl_orders' not in locals():
        # אם המשתמש סיפק tp_targets אבל לא סיפק SL, נכין SL דיפולט
        _, sl_orders = _default_tp_sl(base, side)
    # SL לכל הכמות כדי שיהיה כיסוי מלא
    for s in sl_orders:
        s.setdefault("qty", qty)

    result = {
        "ok": True,
        "symbol": symbol,
        "side": side,
        "leverage": int(req.leverage),
        "base_price": float(base),
        "dry_run": bool(req.dry_run),
        "entry_policy": "HYBRID_LIMIT_STOP(120.0/20.0bps)+MARKET_ESCALATION",
        "gate": {"enter_ok": True, "score": 6.0, "reasons": [], "metrics": {}},
        "risk": {"ok": True, "score": 100.0, "reasons": [],
                 "metrics": {"spread_bps": 0.01}, "symbol": symbol, "side": side, "lev": int(req.leverage)},
        "alloc_ok": True,
        "alloc_error": None,
        "guards": {"percent_price_bps": 0.0, "slippage_guard_bps": 80.0},
        "position_side": "BOTH",
        "reduce_only": False,
        "budget_used": float(req.budget_usd or 0.0),
        "quality": 6.0,
        "adx": 100.0,
        "qty": qty,
        "tp_orders": tp_orders,
        "sl_orders": sl_orders,
        "entry_simulation": {
            "limit_around": float(base * (1 - 0.012 * _sign(side))),
            "stop_around":  float(base * (1 + 0.010 * _sign(side))),
            "escalate_after_sec": 10.0,
            "escalate_slip_bps": 15.0,
            "allow_market_entry": True,
        },
    }
    if req.entry is not None:
        result["entry_price"] = float(req.entry)
    return result

# ---------- אישור טלגרם (URL buttons) ----------
_PENDING: Dict[str, Dict[str, Any]] = {}
_PENDING_TTL = 120  # שניות

def _base_host(request: Request) -> str:
    host = os.getenv("PUBLIC_HOST", "").strip()
    if host:
        return host.rstrip("/")
    # fallback – נגזר מהבקשה
    return f"{request.url.scheme}://{request.url.netloc}"

def _mk_approval(symbol: str, side: str, leverage: int, budget: float,
                 request: Request, result_preview: Dict[str, Any]) -> Dict[str, Any]:
    aid  = secrets.token_urlsafe(16)
    tok  = secrets.token_urlsafe(12)
    now  = time.time()
    _PENDING[aid] = {
        "token": tok,
        "expires": now + _PENDING_TTL,
        "req": {"symbol": symbol, "side": side, "leverage": leverage, "budget_usd": budget},
        "result": result_preview,
    }
    base = _base_host(request)
    approve_url = f"{base}/ops/approve?aid={aid}&tok={tok}"
    reject_url  = f"{base}/ops/reject?aid={aid}&tok={tok}"
    return {"id": aid, "token": tok, "approve_url": approve_url, "reject_url": reject_url}

def _telegram_send(text: str, approve_url: str, reject_url: str) -> None:
    bot = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat= os.getenv("TELEGRAM_APPROVAL_CHAT_ID", "").strip()
    if not bot or not chat:
        return
    import httpx
    kb = {
        "inline_keyboard": [[
            {"text": "✅ Approve", "url": approve_url},
            {"text": "❌ Reject",  "url": reject_url},
        ]]
    }
    try:
        with httpx.Client(timeout=10.0) as cli:
            cli.post(f"https://api.telegram.org/bot{bot}/sendMessage",
                     json={"chat_id": chat, "text": text, "reply_markup": kb, "disable_web_page_preview": True})
    except Exception:
        pass

# ---------- המסלול ----------
@router.post("/trade/execute")
def trade_execute(
    req: TradeRequest,
    request: Request,
    _token: str = Depends(require_api_key),
    x_idempotency_key: Optional[str] = Header(default=None, alias="X-Idempotency-Key"),
):
    # Idempotency
    idem = _idem_check(x_idempotency_key, req.dry_run)
    if idem is not None and not req.dry_run:
        return idem

    # נבנה תוצאה דינמית
    res = _build_result(req)

    # Auto-approve? אם לא – שלח טלגרם לאישור
    auto_approve = os.getenv("TELEGRAM_AUTO_APPROVE", "0").lower() in ("1", "true", "yes", "on")
    if req.confirm_first and not auto_approve:
        ap = _mk_approval(req.symbol.upper(), req.side, int(req.leverage), float(req.budget_usd or 0.0),
                          request=request, result_preview=res)
        _telegram_send(
            text=f"Trade request\nSymbol: {req.symbol.upper()}\nSide: {req.side}\nLev: {req.leverage}\nBudget: {req.budget_usd or 0.0}\nDryRun: {req.dry_run}\n\nTap to approve/reject.",
            approve_url=ap["approve_url"], reject_url=ap["reject_url"]
        )
        return JSONResponse(status_code=200, content={
            "ok": True, "pending_approval": True,
            "approve_url": ap["approve_url"], "reject_url": ap["reject_url"],
            "result_preview": res
        })

    # אחרת – ממשיכים מיד (dry_run — סימולציה; בפועל הייתם מכניסים כאן שליחת הוראה לברוקר)
    return JSONResponse(status_code=200, content={"ok": True, "error": None, "result": res})



































































































































































































































































































































































































































































































































































































































































