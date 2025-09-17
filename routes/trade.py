# routes/trade.py
from __future__ import annotations
import os, time, asyncio, secrets
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator
import httpx

from utils.auth import require_api_key
from utils.binance_trade import plan_and_execute

router = APIRouter(tags=["trade"])

# ===== pending store לאישורים (in-memory קל) =====
_PENDING: Dict[str, Dict[str, Any]] = {}  # idem -> payload
_PENDING_TTL = 60 * 5  # 5 דקות

def _make_idem(x_idem: Optional[str]) -> str:
    return x_idem or f"{int(time.time()*1000)}_{secrets.token_hex(6)}"

def _auto_approve() -> bool:
    return os.getenv("TELEGRAM_AUTO_APPROVE", "").lower() in ("1", "true", "yes", "on")

async def _send_telegram_approval(idem: str, summary: str) -> None:
    bot = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.getenv("TELEGRAM_APPROVAL_CHAT_ID", "").strip()
    public = os.getenv("PUBLIC_HOST", "").strip()
    if not bot or not chat or not public:
        return
    approve_url = f"{public.rstrip('/')}/trade/approve?id={idem}"
    reject_url  = f"{public.rstrip('/')}/trade/reject?id={idem}"
    kb = {
        "inline_keyboard": [[
            {"text": "✅ Approve", "url": approve_url},
            {"text": "❌ Reject",  "url": reject_url},
        ]]
    }
    async with httpx.AsyncClient(timeout=10.0) as cli:
        await cli.post(f"https://api.telegram.org/bot{bot}/sendMessage", json={
            "chat_id": chat,
            "text": f"Trade request pending:\n{summary}\n\nIdem: {idem}",
            "reply_markup": kb,
            "disable_web_page_preview": True,
        })

class TradeReq(BaseModel):
    symbol: str
    side: str
    leverage: int = Field(ge=1, le=125)
    budget_usd: float = Field(gt=0)
    dry_run: bool = False
    confirm_first: bool = False
    entry: Optional[float] = None
    tp_targets: Optional[List[float]] = None
    tp_splits: Optional[List[float]] = None

    @field_validator("side")
    @classmethod
    def _side_ok(cls, v: str) -> str:
        if v.upper() not in ("BUY", "SELL"):
            raise ValueError("side must be BUY or SELL")
        return v

    @field_validator("tp_splits")
    @classmethod
    def _splits_sum_ok(cls, v: Optional[List[float]], info):
        if v is not None:
            s = sum(v)
            if s > 1.0 + 1e-9:
                raise ValueError("sum(tp_splits) must be <= 1")
        return v

def _422(detail: Any) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail)

def _summary(req: TradeReq) -> str:
    return f"{req.side.upper()} {req.symbol.upper()} lev={req.leverage} budget=${req.budget_usd} dry_run={req.dry_run}"

@router.post("/trade/execute")
async def trade_execute(
    req: TradeReq,
    request: Request,
    _token: str = Depends(require_api_key),
    x_idem: Optional[str] = Header(default=None, alias="X-Idempotency-Key"),
) -> Dict[str, Any]:
    # ולידציות 422 המתבקשות
    if req.entry is not None and req.entry < 0:
        raise _422([{"type":"value_error","loc":["body","entry"],"msg":"entry must be >= 0","input": req.entry}])

    idem = _make_idem(x_idem)

    # אם confirm_first וה־auto_approve לא דולק → שומרים כ־pending ושולחים כפתורים בטלגרם
    if req.confirm_first and not _auto_approve() and not req.dry_run:
        _PENDING[idem] = {"ts": time.time(), "req": req.model_dump()}
        try:
            await _send_telegram_approval(idem, _summary(req))
        except Exception:
            pass
        return {"ok": False, "error": "pending_approval", "result": {"reason": "pending", "idem": idem, "ttl_sec": _PENDING_TTL}}

    # אחרת — מבצעים עכשיו (LIVE / DRY-RUN)
    try:
        res = await plan_and_execute(
            symbol=req.symbol,
            side=req.side,
            leverage=req.leverage,
            budget_usd=req.budget_usd,
            tp_targets=req.tp_targets,
            tp_splits=req.tp_splits,
            sl_price=req.entry if (req.entry and req.entry > 0) else None,
            dry_run=bool(req.dry_run),
        )
        return {"ok": True, "error": None, "result": res}
    except ValueError as ve:
        # הפוך ל־422
        raise _422([{"type":"value_error","loc":["body"],"msg":str(ve)}])
    except httpx.HTTPStatusError as he:
        # שגיאה מבינאנס – נחזיר 502 עם גוף
        raise HTTPException(status_code=502, detail={"error":"binance_http", "status": he.response.status_code, "body": he.response.text})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ---- אישור/דחייה (כפתורי טלגרם) ----
@router.get("/trade/approve", include_in_schema=False)
async def trade_approve(id: str) -> Dict[str, Any]:
    item = _PENDING.pop(id, None)
    if not item:
        return {"ok": False, "error": "not_found_or_expired"}
    req = TradeReq(**item["req"])
    try:
        res = await plan_and_execute(
            symbol=req.symbol, side=req.side, leverage=req.leverage, budget_usd=req.budget_usd,
            tp_targets=req.tp_targets, tp_splits=req.tp_splits,
            sl_price=req.entry if (req.entry and req.entry > 0) else None,
            dry_run=False,
        )
        return {"ok": True, "result": res}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@router.get("/trade/reject", include_in_schema=False)
async def trade_reject(id: str) -> Dict[str, Any]:
    _PENDING.pop(id, None)
    return {"ok": True, "rejected": True}





































































































































































































































































































































































































































































































































































































































































