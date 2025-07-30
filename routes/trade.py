from fastapi import APIRouter, Query, HTTPException
from utils.multi_tf_scanner import multi_tf_scan_with_ai
from utils.trade_storage import find_trade, load_open_trades, update_trade
from utils.get_live_price import get_live_price  # אתה צריך שתהיה לך פונקציה כזו, מחזירה מחיר עדכני

router = APIRouter()
trade_cache = []

@router.get("/get-trade-status")
async def get_trade_status(
    symbol: str = Query(..., description="סימבול הטרייד, לדוג' BTCUSDT"),
    direction: str = Query(..., description="כיוון הטרייד: LONG/SHORT")
):
    """
    מחזיר סטטוס חי של טרייד פתוח (רווח/הפסד, מחיר נוכחי, סטופ/טייק, מצב מגמה).
    """
    trade = find_trade(symbol, direction)
    if not trade:
        return {"message": f"לא נמצא טרייד פתוח על {symbol} {direction}"}

    try:
        # מחיר עדכני מה־API
        live_price = get_live_price(symbol)
        entry = float(trade["entry"])
        sl = float(trade.get("sl", 0))
        tp = float(trade.get("tp", 0))
        leverage = int(trade.get("leverage", 20))
        direction = trade["direction"].upper()
        # רווח/הפסד באחוזים
        if direction == "LONG":
            pnl = ((live_price - entry) / entry) * leverage * 100
        else:  # SHORT
            pnl = ((entry - live_price) / entry) * leverage * 100

        # האם הגיע ל־TP או SL?
        closed = None
        if direction == "LONG" and sl > 0 and live_price <= sl:
            closed = "הגיע ל־SL (הפסד)"
        if direction == "LONG" and tp > 0 and live_price >= tp:
            closed = "הגיע ל־TP (רווח)"
        if direction == "SHORT" and sl > 0 and live_price >= sl:
            closed = "הגיע ל־SL (הפסד)"
        if direction == "SHORT" and tp > 0 and live_price <= tp:
            closed = "הגיע ל־TP (רווח)"

        # (אופציונלי) – ניתוח מגמה ו-AI:
        ai_opinion = trade.get("ai_opinion", "")

        result = {
            "symbol": symbol,
            "direction": direction,
            "entry": entry,
            "current_price": live_price,
            "sl": sl,
            "tp": tp,
            "leverage": leverage,
            "pnl_percent": round(pnl, 2),
            "status": "סגור" if closed else "פעיל",
            "reason": closed if closed else "",
            "ai_opinion": ai_opinion,
            "opened_at": trade.get("opened_at", ""),
        }
        # עדכן אם נסגר
        if closed:
            trade["status"] = "סגור"
            update_trade(trade)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


