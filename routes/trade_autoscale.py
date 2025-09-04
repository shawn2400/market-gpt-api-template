# routes/trade_autoscale.py
from __future__ import annotations
import os, logging
from typing import Dict, Any, Optional
from fastapi import APIRouter, Depends, Body
from fastapi.responses import JSONResponse
import math, httpx

try:
    from utils.auth import require_api_key
    _deps = [Depends(require_api_key)]
except Exception:
    _deps = []

logger = logging.getLogger("algogpt.autoscale")
router = APIRouter(prefix="/trade/autoscale", tags=["Trade"], dependencies=_deps)

# לצורך הדמו, נציג פרמטרים פשוטים:
# policy: מוסיף פוזיציה כשה־unrealized>=TP1/2, ADX>25, ATR יציב, drawdown<% מסוים.

def _policy_should_add(ctx: Dict[str, Any]) -> Dict[str, Any]:
    # ctx דוגמה:
    # { "symbol": "BTCUSDT", "side":"LONG","unrealized_pct": 1.8, "adx":27, "atr": 120, "vol_ok": True, "risk_pct": 0.7 }
    u = float(ctx.get("unrealized_pct", 0.0))
    adx = float(ctx.get("adx", 0.0))
    vol_ok = bool(ctx.get("vol_ok", True))
    risk_pct = float(ctx.get("risk_pct", 1.0))
    if not vol_ok: return {"ok": False, "reason": "low_volume"}
    if adx < 25: return {"ok": False, "reason": "weak_trend"}
    if u < 1.0: return {"ok": False, "reason": "insufficient_profit"}
    if risk_pct > 2.0: return {"ok": False, "reason": "risk_cap_reached"}
    # הוספה שמרנית: 25–33% מהפוזיציה
    scale_pct = 0.25 if u < 2.0 else 0.33
    return {"ok": True, "scale_pct": scale_pct}

async def _notify(text: str):
    token = os.getenv("TELEGRAM_BOT_TOKEN","").strip()
    chat  = os.getenv("ADMIN_CHAT_ID","").strip()
    if not token or not chat:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=8.0) as cli:
            await cli.post(url, json={"chat_id": int(chat), "text": text, "parse_mode":"Markdown"})
    except Exception:
        pass

@router.post("/propose")
async def propose(payload: Dict[str, Any] = Body(...)):
    """
    קלט מינימלי לדוגמה:
    {
      "symbol":"BTCUSDT","side":"LONG",
      "position_qty": 0.05, "entry": 61000, "current": 61820,
      "unrealized_pct": 1.35, "adx": 27, "atr": 120, "vol_ok": true,
      "risk_pct": 0.7
    }
    """
    chk = _policy_should_add(payload)
    if not chk.get("ok"):
        return {"ok": False, "reason": chk.get("reason")}

    pos_qty = float(payload.get("position_qty", 0.0))
    scale_qty = round(pos_qty * float(chk["scale_pct"]), 6)
    text = (
        f"🟡 *Auto-Scale Proposal* for {payload.get('symbol')} ({payload.get('side')})\n"
        f"• unrealized={payload.get('unrealized_pct')}%\n"
        f"• adx={payload.get('adx')}, atr={payload.get('atr')}\n"
        f"• add qty ≈ *{scale_qty}*\n\n"
        f"שלח /approve_autoscale {payload.get('symbol')} {scale_qty} כדי לאשר."
    )
    await _notify(text)
    return {"ok": True, "suggested_qty": scale_qty}

@router.post("/confirm")
async def confirm(payload: Dict[str, Any] = Body(...)):
    """
    מאשר הגדלת כמות — כאן אפשר לשלב קריאה לפונקציה קיימת שמבצעת Order אמיתי.
    קלט:
      { "symbol":"BTCUSDT", "side":"BUY", "qty": 0.012, "reduce_only": false }
    """
    # כאן תוכל לשלב את ה-executor שלך לביצוע אמיתי (market/limit),
    # אנחנו נשיב הודעה ונניח שאתה מבצע דרך /trade/execute או utils.order_hygiene.
    await _notify(f"🟢 *Approved Autoscale*: {payload}")
    return {"ok": True, "executed": False, "note": "Wire this to your live executor endpoint."}
