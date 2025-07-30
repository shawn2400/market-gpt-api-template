# routes/trade.py

from fastapi import APIRouter, Query, HTTPException
from utils.multi_tf_scanner import multi_tf_scan_with_ai
from utils.trade_storage import find_trade, load_open_trades, update_trade, add_trade
from utils.get_live_price import get_live_price

router = APIRouter()
trade_cache = []

@router.get("/get-trade")
async def get_trade(
    budget: float = Query(100, description="סכום השקעה מוצע (אפשר לשנות)")
):
    """
    מחזיר טרייד איכותי (quality 5+), בכל טיימפריים מ-5m עד 4h בלבד.
    אם אין – מחזיר הודעה ברורה.
    """
    try:
        frames = "5m,15m,30m,1h,4h"
        min_quality = 5
        timeframes = [f.strip() for f in frames.split(",")]
        trades = await multi_tf_scan_with_ai(
            timeframes=timeframes,
            min_quality=min_quality,
            top=25
        )
        # רק טריידים שה-AI תומך בכיוון (אם קיים AI)
        smart_trades = [
            t for t in trades
            if t.get("ai_opinion") and t["main_direction"].lower() in t["ai_opinion"].lower() and "error" not in t["ai_opinion"].lower()
        ] if trades else []
        candidates = smart_trades if smart_trades else trades
        for trade in candidates:
            sig = (trade["symbol"], trade["main_direction"], trade["frames"][0])
            if sig not in trade_cache:
                trade_cache.append(sig)
                if len(trade_cache) > 100: trade_cache.pop(0)
                volume = trade.get("details", [{}])[0].get("volume", 1_000_000)
                suggested_budget = min(max(100, float(volume) * 0.001), 1000)
                # שמירה לטריידים פתוחים
                add_trade({
                    "symbol": trade["symbol"],
                    "direction": trade["main_direction"],
                    "entry": trade["details"][-1]["close"],
                    "sl": trade["details"][-1].get("sl"),
                    "tp": trade["details"][-1].get("tp"),
                    "leverage": 20,
                    "opened_at": trade["details"][-1].get("time", ""),
                    "ai_opinion": trade.get("ai_opinion", ""),
                    "status": "פעיל"
                })
                return {
                    "symbol": trade["symbol"],
                    "direction": trade["main_direction"],
                    "entry": trade["details"][-1]["close"],
                    "sl": trade["details"][-1].get("sl"),
                    "tp": trade["details"][-1].get("tp"),
                    "leverage": 20,
                    "suggested_budget": round(suggested_budget, 2),
                    "your_budget": budget,
                    "quality": trade["avg_quality"],
                    "frames": trade["frames"],
                    "ai_opinion": trade.get("ai_opinion", ""),
                    "details": trade["details"]
                }
        # אין quality 5+ בכל ה-frames
        return {"message": "אין טריידים איכותיים כרגע (quality 5+). נסה שוב מאוחר יותר."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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



