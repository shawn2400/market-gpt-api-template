# utils/trade_validator.py
from __future__ import annotations
from typing import Dict, Any, Optional, List
import os

from utils.risk_rules import gate_trade, rr_from_levels, entry_gap_ok

# התנהגות ברירת מחדל:
# - שגיאות חוסמות (errors) יגרמו ok=False
# - אזהרות (warnings) אינן חוסמות
# ניתן לשנות ספים בעתיד לפי interval/market אם תרצה
DEFAULT_VOL_REGIME = os.getenv("DEFAULT_VOL_REGIME", "mid")


def _is_directional_payload(p: Dict[str, Any]) -> bool:
    side = (p.get("side") or "").upper()
    has_lvls = (p.get("entry") is not None) and (p.get("sl") is not None) and (p.get("tp1") is not None)
    return side in ("LONG", "SHORT") and has_lvls


async def validate_proposal(
    proposal: Dict[str, Any],
    *,
    interval: str = "15m",
    market: str = "futures",
) -> Dict[str, Any]:
    """
    ולידציה מקדימה לטריידים נכנסים מהוורקר/בוט.
    תומך בשני מודלים:
      1) טרייד כיווני (FUTURES/SPOT): side+entry+sl+tp1 → נבדק קשיח דרך gate_trade.
      2) הצעת GRID/לא-כיוונית: אם אין side/levels → ok=True עם אזהרה רכה.
    """
    errors: List[str] = []
    warnings: List[str] = []

    symbol = (proposal.get("symbol") or "").upper().strip()
    if not symbol:
        errors.append("missing symbol")

    price = proposal.get("current_price", None)
    try:
        if price is not None and float(price) <= 0:
            errors.append("bad current_price")
    except Exception:
        errors.append("bad current_price")

    # זיהוי מודל
    if not _is_directional_payload(proposal):
        # כנראה GRID/לא-כיווני — לא נחסום
        warnings.append("non-directional payload (skipping RR/levels checks)")
        return {"ok": len(errors) == 0, "errors": errors, "warnings": warnings}

    side = (proposal.get("side") or "").upper()
    entry = proposal.get("entry")
    sl    = proposal.get("sl")
    tp1   = proposal.get("tp1")
    leverage = proposal.get("leverage")
    success_pct = proposal.get("success_pct")

    # שער ראשי (כולל בדיקת סדר רמות, מרחק כניסה, RR ומינוף)
    g = gate_trade(
        symbol=symbol,
        side=side,
        price=price,
        entry=entry,
        sl=sl,
        tp1=tp1,
        vol_regime=DEFAULT_VOL_REGIME,
        success_pct=success_pct,
        leverage=leverage,
    )
    if not g["ok"]:
        errors.extend(g.get("errors", []))
    warnings.extend(g.get("warnings", []))

    # בדיקות רכות נוספות (לא חוסם):
    # סטופ צמוד מדי למחיר (מתחת ~0.15% מהמחיר)
    try:
        e = float(entry); s = float(sl); p = float(price)
        stop_gap_pct = abs(e - s) / p * 100.0 if p > 0 else None
        if stop_gap_pct is not None and stop_gap_pct < 0.15:
            warnings.append(f"stop very tight (~{stop_gap_pct:.3f}%)")
    except Exception:
        pass

    return {"ok": len(errors) == 0, "errors": errors, "warnings": warnings}


