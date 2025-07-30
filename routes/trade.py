# routes/trade.py

from fastapi import APIRouter, Query, HTTPException
from utils.multi_tf_scanner import multi_tf_scan_with_ai
from utils.trade_storage import find_trade, load_open_trades, update_trade, add_trade
from utils.get_live_price import get_price as get_live_price
from utils.grid_utils import execute_grid

router = APIRouter()
trade_cache = []

@router.get("/get-trade")
async def get_trade(
    budget: float = Query(100, description="סכום השקעה מוצע (אפשר לשנות)"),
    use_grid: bool = Query(False, description="הפעלת גריד?"),
    grid_count: int = Query(8, description="מספר רמות בגריד (אם נבחר)"),
    grid_pct: float = Query(0.5, description="אחוז סטיית גריד בין רמות (אם נבחר)")
):
    """
    מחזיר טרייד איכותי (quality 5+), בכל טיימפריים מ-5m עד 4h בלבד.
    מאפשר גם טרייד רגיל וגם טרייד גריד. מראה ללקוח המלצת תקציב, מסלול, איכות, וכל הפרטים.
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
        # סינון: טריידים עם תמיכת AI
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
                # טרייד רגיל או Grid
                if use_grid:
                    grid_orders = execute_grid(
                        symbol=trade["symbol"],
                        budget=budget,
                        grid_count=grid_count,
                        grid_pct=grid_pct,
                        leverage=20,
                        futures=True,
                        direction="BOTH",
                        tp_pct=1,
                        sl_pct=1
                    )
                    trade_type = "GRID"
                    # שמור grid כתוספת ב־open_trades.json
                    add_trade({
                        "symbol": trade["symbol"],
                        "direction": trade["main_direction"],
                        "entry": trade["details"][-1]["close"],
                        "type": "GRID",
                        "leverage": 20,
                        "opened_at": trade["details"][-1].get("time", ""),
                        "ai_opinion": trade.get("ai_opinion", ""),
                        "grid_levels": [g["price"] for g in grid_orders],
                        "status": "פעיל"
                    })
                    return {
                        "symbol": trade["symbol"],
                        "direction": trade["main_direction"],
                        "entry": trade["details"][-1]["close"],
                        "type": "GRID",
                        "leverage": 20,
                        "suggested_budget": round(suggested_budget, 2),
                        "your_budget": budget,
                        "quality": trade["avg_quality"],
                        "frames": trade["frames"],
                        "ai_opinion": trade.get("ai_opinion", ""),
                        "details": trade["details"],
                        "grid_orders": grid_orders
                    }
                else:
                    # רגיל
                    add_trade({
                        "symbol": trade["symbol"],
                        "direction": trade["main_direction"],
                        "entry": trade["details"][-1]["close"],
                        "sl": trade["details"][-1].get("sl"),
                        "tp": trade["details"][-1].get("tp"),
                        "leverage": 20,
                        "opened_at": trade["details"][-1].get("time", ""),
                        "ai_opinion": trade.get("ai_opinion", ""),
                        "type": "REGULAR",
                        "status": "פעיל"
                    })
                    return {
                        "symbol": trade["symbol"],
                        "direction": trade["main_direction"],
                        "entry": trade["details"][-1]["close"],
                        "type": "REGULAR",
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




