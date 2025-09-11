# utils/trade_execution_core.py
from __future__ import annotations
from typing import Dict, Any, Optional

__all__ = ["dry_run_trade"]


def _pct_change(new: float, ref: float) -> float:
    """החזרת שינוי באחוזים בין new ל-ref (תמיד ערך מוחלט עבור SL, חתום עבור TP)."""
    if ref <= 0:
        return 0.0
    return (new / ref - 1.0) * 100.0


def dry_run_trade(
    symbol: str,
    side: str,              # "LONG" | "SHORT" | "BUY" | "SELL"
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

    פרמטרים:
      symbol       - סימבול (למשל "BTCUSDT")
      side         - "LONG"/"SHORT" (תומך גם "BUY"/"SELL" לנוחות)
      entry        - מחיר כניסה משוער
      sl / tp      - סטופ/טייק (אופציונליים; אם חסרים נייצר מינימום עדין)
      leverage     - מינוף (int >= 1)
      budget       - תקציב בדולרים לפתיחה (לא נדרש יתרה בפועל כי זה DRY)
      market_type  - ברירת מחדל "futures" (למטרות תיוג בלבד)

    מחזיר:
      dict עם פרטי ה־DRY-RUN: כמות משוערת, SL/TP משוערים, אחוזים, יחס R:R ועוד.
    """
    if not isinstance(symbol, str) or not symbol:
        raise ValueError("symbol is required")
    if entry is None or entry <= 0:
        raise ValueError("entry must be a positive number")
    if leverage is None or leverage < 1:
        raise ValueError("leverage must be >= 1")
    if budget is None or budget <= 0:
        raise ValueError("budget must be > 0")

    # Normalize side (קבלה גם BUY/SELL)
    side_up = str(side or "").upper().strip()
    if side_up in ("BUY", "LONG"):
        norm_side = "LONG"
    elif side_up in ("SELL", "SHORT"):
        norm_side = "SHORT"
    else:
        raise ValueError("side must be LONG/SHORT (or BUY/SELL)")

    # אם אין SL/TP – גוזרים מינימום עדין כדי לא להעמיס חישובים
    # ברירת מחדל שמרנית: SL 0.3% | TP 0.6% מהכניסה
    min_sl_pct = 0.003  # 0.3%
    min_tp_pct = 0.006  # 0.6%
    if sl is None or tp is None:
        if norm_side == "LONG":
            sl = sl or round(entry * (1 - min_sl_pct), 2)
            tp = tp or round(entry * (1 + min_tp_pct), 2)
        else:
            sl = sl or round(entry * (1 + min_sl_pct), 2)
            tp = tp or round(entry * (1 - min_tp_pct), 2)

    # כמות משוערת (DRY): notional ≈ budget*leverage
    qty_est = round(budget * leverage / max(entry, 1e-9), 6)
    notional_usd = round(qty_est * entry, 2)
    exposure_usd = round(budget * leverage, 2)

    # אחוזי SL/TP יחסית לכניסה
    if norm_side == "LONG":
        sl_pct = abs(_pct_change(float(sl), entry))
        tp_pct = _pct_change(float(tp), entry)  # חיובי צפוי
    else:
        # SHORT: מחיר נמוך יותר הוא רווח; גבוה הוא הפסד
        sl_pct = abs(_pct_change(entry, float(sl)))   # כמה נגדנו עד ל-SL
        tp_pct = abs(_pct_change(entry, float(tp)))   # כמה לטובתנו עד ל-TP

    # יחס R:R בקירוב (TP% / SL%), אם תקין
    rr = round(tp_pct / sl_pct, 3) if sl_pct > 0 else None

    # רווח/הפסד משוער בדולרים (תיאורטי, ללא עמלות/סליפג')
    # Δמחיר * כמות; ב-SHORT, שינוי שלילי במחיר הוא רווח → משתמשים בערכים מוחלטים
    if norm_side == "LONG":
        tp_pnl = round((float(tp) - entry) * qty_est, 2)
        sl_pnl = round((float(sl) - entry) * qty_est, 2)  # שלילי צפוי
    else:
        tp_pnl = round((entry - float(tp)) * qty_est, 2)
        sl_pnl = round((entry - float(sl)) * qty_est, 2)  # שלילי צפוי (הפסד)

    return {
        "ok": True,
        "dry_run": True,
        "symbol": symbol.upper(),
        "side": norm_side,            # LONG / SHORT
        "market_type": market_type,
        "entry": float(entry),
        "sl": float(sl),              # מחירים משוערים
        "tp": float(tp),
        "leverage": int(leverage),
        "budget_usd": float(budget),
        "qty_est": qty_est,
        "notional_usd_est": notional_usd,
        "exposure_usd_est": exposure_usd,
        "metrics": {
            "sl_pct": round(sl_pct, 4),
            "tp_pct": round(tp_pct, 4),
            "rr": rr,
            "tp_pnl_usd_est": tp_pnl,
            "sl_pnl_usd_est": sl_pnl,
        },
        "notes": [
            "DRY-RUN בלבד – לא מבצע הזמנות בפועל.",
            "החישוב תיאורטי, ללא עמלות/סליפג׳/מסי מימון.",
        ],
    }







