# routes/trade.py
from fastapi import APIRouter, HTTPException, Query, Depends
from typing import Optional
from utils.auth import require_bearer_token
from utils.multi_tf_scanner import multi_tf_scan_with_ai
from utils.ai_analysis import predict_optimal_sl_tp

router = APIRouter(tags=["Trades"], dependencies=[Depends(require_bearer_token)])

@router.get("/trade/best")
async def get_best_trade(
    min_quality: int = Query(6, ge=1, le=10, description="ציון איכות מינימלי"),
    top: int = Query(1, ge=1, description="מספר הטריידים שברצונך לקבל"),
    timeframes: Optional[str] = Query("5m,15m,1h", description="טיימפריימים"),
    market_type: Optional[str] = Query("futures", description="סוג שוק"),
    trending_only: Optional[bool] = Query(True, description="האם לסנן רק טרנדים"),
    trending_source: Optional[str] = Query("coingecko", description="מקור טרנדים")
):
    tfs = tuple(tf.strip() for tf in timeframes.split(","))
    results = await multi_tf_scan_with_ai(
        timeframes=tfs,
        markets=(market_type,),
        min_quality=min_quality,
        top=top,
        trending_only=trending_only,
        trending_source=trending_source
    )
    if not results:
        raise HTTPException(status_code=404, detail="לא נמצאו טריידים איכותיים כרגע")
    best_trade = results[0]
    sl, tp = await predict_optimal_sl_tp(
        symbol=best_trade["symbol"],
        direction=best_trade["direction"],
        entry_price=best_trade.get("entry") or 0,
        atr=best_trade.get("atr")
    )
    trade_info = {
        "symbol": best_trade["symbol"],
        "direction": best_trade["direction"],
        "quality_score": best_trade["quality_score"],
        "entry": best_trade.get("entry") or "שימוש במחיר שוק",
        "sl": sl,
        "tp": tp,
        "leverage": 10,
        "budget_usd": 100,
    }
    return {"best_trade": trade_info}




