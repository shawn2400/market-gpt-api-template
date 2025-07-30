# routes/trade.py

from fastapi import APIRouter, Query, HTTPException
from utils.multi_tf_scanner import multi_tf_scan_with_ai

router = APIRouter()

# שמירה על זיכרון של טריידים שנשלחו (בריצה הנוכחית של השרת)
trade_cache = []

@router.get("/get-trade")
async def get_trade(
    min_quality: int = Query(5, description="סף איכות מינימלי לטרייד"),
    frames: str = Query("5m,15m,1h,4h,1d", description="טיימפריימים לבדיקה (פסיק ביניהם)"),
    budget: float = Query(100, description="סכום השקעה מומלץ (אפשר לבחור אחר כך)"),
    top: int = Query(25, description="כמה טריידים לסרוק במקסימום")
):
    """
    מחזיר טרייד איכותי, כולל המלצה חכמה לסכום השקעה, מחיר, SL, TP, מינוף – מוכן להעתקה לביננס.
    אפשר לבקש 'תן לי טרייד', ואם לא רוצים – לבקש שוב 'תן חדש'.
    """
    try:
        timeframes = [f.strip() for f in frames.split(",")]
        trades = await multi_tf_scan_with_ai(
            timeframes=timeframes,
            min_quality=min_quality,
            top=top
        )
        # אפשרות להגדיר קריטריון של המלצת AI חזקה בלבד (למשל שה-AI בעד הכיוון)
        smart_trades = [
            t for t in trades
            if t.get("ai_opinion") and t["main_direction"].lower() in t["ai_opinion"].lower() and "error" not in t["ai_opinion"].lower()
        ] if trades else []
        candidates = smart_trades if smart_trades else trades

        # סינון כפילויות: לא להחזיר אותו טרייד פעמיים רצוף
        for trade in candidates:
            sig = (trade["symbol"], trade["main_direction"], trade["frames"][0])
            if sig not in trade_cache:
                trade_cache.append(sig)
                # ננקה cache אם נהיה ארוך מדי
                if len(trade_cache) > 100: trade_cache.pop(0)

                # הערכת סכום השקעה מומלץ (דוגמה: 1% מהווליום ב־frame הראשי, מוגבל ל־1000)
                volume = trade.get("details", [{}])[0].get("volume", 1_000_000)
                suggested_budget = min(max(100, float(volume) * 0.001), 1000)
                # אפשרות לשים לוגיקה חכמה יותר (למשל לבדוק margin/minimum order לפי ביננס בפועל)
                return {
                    "symbol": trade["symbol"],
                    "direction": trade["main_direction"],
                    "entry": trade["details"][-1]["close"],
                    "sl": trade["details"][-1].get("sl"),
                    "tp": trade["details"][-1].get("tp"),
                    "leverage": 20,  # אפשר להחליף למשהו דינמי אם רוצים
                    "suggested_budget": round(suggested_budget, 2),
                    "your_budget": budget,
                    "quality": trade["avg_quality"],
                    "frames": trade["frames"],
                    "ai_opinion": trade.get("ai_opinion", ""),
                    "details": trade["details"]
                }

        # אם לא מצאנו חדש – מחזירים הודעה כללית
        return {"message": "אין כרגע טרייד חדש שעומד בכללים. נסה שוב בעוד דקה או שנה הגדרות."}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

