# routes/order_modify.py
from __future__ import annotations

from fastapi import APIRouter, Depends, Body, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, Literal, Dict, Any

from utils.auth import require_api_key
from utils.binance_client import (
    get_order, cancel_order, get_open_orders,
    place_stop_market_order, place_take_profit_market,
)

router = APIRouter(
    prefix="/trade",
    tags=["Trade-Modify"],
    dependencies=[Depends(require_api_key)],
)

class UpdateOrderReq(BaseModel):
    symbol: str = Field(..., examples=["BTCUSDT"])
    orderId: Optional[int] = Field(None, description="Binance orderId")
    clientId: Optional[str] = Field(None, description="origClientOrderId")
    new_price: float = Field(..., gt=0, description="new stopPrice/trigger")
    type: Literal["TP", "SL"] = Field(..., description="איזה טריגר לעדכן")

def _detect_order_kind(order: Dict[str, Any]) -> str:
    """
    מחזיר "STOP_MARKET" או "TAKE_PROFIT_MARKET" או מחרוזת ריקה אם לא מזוהה.
    """
    ot = (order.get("type") or "").upper()
    if ot in ("STOP_MARKET", "TAKE_PROFIT_MARKET"):
        return ot
    # חלק מהנהלים מחזירים גם type=STOP/TAKE_PROFIT (גרסאות ישנות) – נתמוך בזה
    if ot == "STOP":
        return "STOP_MARKET"
    if ot == "TAKE_PROFIT":
        return "TAKE_PROFIT_MARKET"
    return ""

def _reverse_side(side: str) -> str:
    s = (side or "").upper()
    return "SELL" if s == "BUY" else "BUY"

@router.post("/update-order")
def update_order(req: UpdateOrderReq = Body(...)) -> Dict[str, Any]:
    """
    עדכון TP/SL לפתיחה קיימת:
    - נשלוף את ההזמנה.
    - אם זה טריגר מסוג מתאים → נבטל וניצור מחדש עם ה-stopPrice החדש.
    - אם זה לא טריגר מוכר, או PUT לא נתמך – מחזירים שגיאה מנומקת.
    """
    if not (req.orderId or req.clientId):
        raise HTTPException(status_code=400, detail="must provide orderId or clientId")

    sym = req.symbol.strip().upper()

    # 1) שליפה
    try:
        ord_ = get_order(sym, order_id=req.orderId, client_id=req.clientId)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"get_order failed: {e}")

    kind = _detect_order_kind(ord_)
    if kind not in ("STOP_MARKET", "TAKE_PROFIT_MARKET"):
        # ננסה עדיין: יש מי שעושה TP/SL כ-LIMIT. במקרה כזה לא "משנים" – צריך לבטל ולפתוח חדש ידנית.
        raise HTTPException(status_code=400, detail=f"order type not modifiable as TP/SL (type={ord_.get('type')})")

    side = (ord_.get("side") or "").upper()
    qty  = ord_.get("origQty") or ord_.get("quantity") or ord_.get("cumQty") or None
    pos_side = ord_.get("positionSide")  # יכול להיות None במצב one-way
    if qty is None:
        # fallback: נשלוף openOrders ונמצא את הכמות שוב (במקרה של שדות שונים)
        try:
            oo = get_open_orders(sym)
            for o in oo:
                if (req.orderId and o.get("orderId") == req.orderId) or \
                   (req.clientId and o.get("clientOrderId") == req.clientId):
                    qty = o.get("origQty") or o.get("quantity")
                    break
        except Exception:
            pass

    try:
        qty_f = float(qty) if qty is not None else None
    except Exception:
        qty_f = None

    if qty_f is None or qty_f <= 0:
        raise HTTPException(status_code=400, detail="cannot resolve order quantity to re-place TP/SL")

    # 2) ביטול
    try:
        cancel_order(sym, order_id=req.orderId, client_id=req.clientId)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"cancel failed: {e}")

    # 3) יצירה מחדש עם מחיר חדש
    try:
        if req.type == "SL":
            if kind != "STOP_MARKET":
                # אם הלקוח סימן SL אבל ההזמנה הייתה TP – נכבד את הקלט וניצור STOP_MARKET
                resp = place_stop_market_order(
                    symbol=sym,
                    side=side,                # צד הסגירה קיים כבר
                    stop_price=float(req.new_price),
                    quantity=qty_f,
                    reduce_only=True,
                    position_side=pos_side,
                )
            else:
                resp = place_stop_market_order(
                    symbol=sym,
                    side=side,
                    stop_price=float(req.new_price),
                    quantity=qty_f,
                    reduce_only=True,
                    position_side=pos_side,
                )
        else:  # "TP"
            if kind != "TAKE_PROFIT_MARKET":
                resp = place_take_profit_market(
                    symbol=sym,
                    side=side,
                    stop_price=float(req.new_price),
                    quantity=qty_f,
                    reduce_only=True,
                    position_side=pos_side,
                )
            else:
                resp = place_take_profit_market(
                    symbol=sym,
                    side=side,
                    stop_price=float(req.new_price),
                    quantity=qty_f,
                    reduce_only=True,
                    position_side=pos_side,
                )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"re-place {req.type} failed: {e}")

    return {
        "ok": True,
        "symbol": sym,
        "orderId_prev": req.orderId,
        "clientId_prev": req.clientId,
        "replaced": kind,
        "new_trigger": float(req.new_price),
        "response": {k: resp.get(k) for k in ("orderId", "clientOrderId", "type", "side", "status", "stopPrice", "origQty")},
    }
