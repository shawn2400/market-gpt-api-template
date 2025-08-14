from typing import Dict, Any, Optional

def dry_run_trade(
    symbol: str,
    side: str,  # LONG | SHORT
    entry: float,
    sl: Optional[float],
    tp: Optional[float],
    leverage: int,
    budget: float,
    market_type: str = "futures",
) -> Dict[str, Any]:
    """
    DRY-RUN בלבד – לא מבצע הזמנת Binance בפועל.
    מיועד להיות קל ומהיר כדי לשמור על 0 עומס.
    """
    side = side.upper()
    assert side in ("LONG", "SHORT"), "side must be LONG or SHORT"

    # אם אין SL/TP – גוזרים מינימום עדין כדי לא להעמיס חישובים
    if sl is None or tp is None:
        min_sl_pct = 0.003  # 0.3%
        min_tp_pct = 0.006  # 0.6%
        if side == "LONG":
            sl = sl or round(entry * (1 - min_sl_pct), 2)
            tp = tp or round(entry * (1 + min_tp_pct), 2)
        else:
            sl = sl or round(entry * (1 + min_sl_pct), 2)
            tp = tp or round(entry * (1 - min_tp_pct), 2)

    # כמות משוערת (DRY)
    qty = round(budget * leverage / max(entry, 1e-9), 6)

    return {
        "symbol": symbol,
        "side": side,
        "entry": entry,
        "sl": sl,
        "tp": tp,
        "leverage": leverage,
        "budget_usd": float(budget),
        "market_type": market_type,
        "qty_est": qty,
        "dry_run": True,
    }






