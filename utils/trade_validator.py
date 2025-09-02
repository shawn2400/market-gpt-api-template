# utils/trade_validator.py
from __future__ import annotations
from typing import Dict, Any, Optional, List
import os
import math

from utils.risk_rules import (
    gate_trade,
    rr_from_levels,
    entry_gap_ok,
    ENTRY_GAP_MAX_PCT,
    ENTRY_GAP_WARN_PCT,
)

# =========================
# Defaults / Tunables
# =========================
DEFAULT_VOL_REGIME = os.getenv("DEFAULT_VOL_REGIME", "mid").strip().lower()
# סף אזהרה ל-RR (לא חוסם; gate_trade מבצע חסימה לפי הכללים שלו)
RR_WARN_THRESHOLD = float(os.getenv("RR_WARN_THRESHOLD", "1.2"))
# לברג' מקסימלי רך לאזהרה (לא חוסם; gate_trade יכול לחסום אם צריך)
SAFE_LEVERAGE_MAX = int(os.getenv("MAX_LEVERAGE", "35"))


def _is_directional_payload(p: Dict[str, Any]) -> bool:
    """
    מזהה אם ה-payload מתאר טרייד כיווני (LONG/SHORT)
    עם רמות מחייבות: entry + sl + tp1
    """
    side = (p.get("side") or "").strip().upper()
    has_lvls = (
        p.get("entry") is not None
        and p.get("sl") is not None
        and p.get("tp1") is not None
    )
    return side in ("LONG", "SHORT") and has_lvls


def _to_float(x: Any) -> Optional[float]:
    try:
        v = float(x)
        if math.isfinite(v):
            return v
        return None
    except Exception:
        return None


def _safe_pct(x: Any) -> Optional[float]:
    v = _to_float(x)
    if v is None:
        return None
    # לא נחסום – רק נחזיר אזהרה אם מחוץ לטווח 0–100
    return v


async def validate_proposal(
    proposal: Dict[str, Any],
    *,
    interval: str = "15m",
    market: str = "futures",
) -> Dict[str, Any]:
    """
    ולידציה מקדימה לטריידים נכנסים מהוורקר/בוט.

    שתי תבניות נתמכות:
      1) טרייד כיווני (LONG/SHORT) עם entry/sl/tp1:
         - חסימה קשיחה דרך gate_trade (כולל סדר רמות, RR לפי הכללים שלך, מרחקי כניסה, ולברג').
         - בנוסף, בדיקות רכות להשלמת תמונה (RR warn, מרחק כניסה warn, סטופ צמוד מידי וכו').
      2) הצעה לא-כיוונית/GRID:
         - לא נחסום; נחזיר ok=True + אזהרה רכה.

    פלט:
      {
        "ok": bool,
        "errors": List[str],
        "warnings": List[str],
        "meta": { ... מידע עזר כמו rr, entry_gap_pct ... }
      }
    """
    errors: List[str] = []
    warnings: List[str] = []
    meta: Dict[str, Any] = {
        "interval": interval,
        "market": market,
        "vol_regime": DEFAULT_VOL_REGIME,
    }

    # --------- שדות בסיסיים ---------
    symbol = (proposal.get("symbol") or "").strip().upper()
    if not symbol:
        errors.append("missing symbol")

    price = _to_float(proposal.get("current_price"))
    if price is not None and price <= 0:
        errors.append("bad current_price")

    # לברג' (אזהרה בלבד; gate_trade הוא הסמכות החוסמת)
    leverage = proposal.get("leverage")
    lev = _to_float(leverage)
    if lev is not None:
        if lev <= 0:
            warnings.append("non-positive leverage (<=0)")
        elif lev > SAFE_LEVERAGE_MAX:
            warnings.append(
                f"leverage high ({lev:g}× > ~{SAFE_LEVERAGE_MAX}×); risk may be elevated"
            )
        meta["leverage"] = lev

    # success % (טווח 0–100 לאזהרה בלבד)
    success_pct = _safe_pct(proposal.get("success_pct"))
    if success_pct is not None:
        meta["success_pct"] = success_pct
        if not (0.0 <= success_pct <= 100.0):
            warnings.append("success_pct out of [0..100] range")

    # אם זה לא טרייד כיווני – לא נחסום (נניח GRID/אחר)
    if not _is_directional_payload(proposal):
        warnings.append("non-directional payload (skipping RR/levels checks)")
        return {
            "ok": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "meta": meta,
        }

    # --------- כיווני: נחלץ רמות ---------
    side = (proposal.get("side") or "").strip().upper()
    entry = _to_float(proposal.get("entry"))
    sl = _to_float(proposal.get("sl"))
    tp1 = _to_float(proposal.get("tp1"))

    if entry is None:
        errors.append("bad entry")
    if sl is None:
        errors.append("bad sl")
    if tp1 is None:
        errors.append("bad tp1")

    # אם יש כבר שגיאות בסיס – עצור לפני gate_trade
    if errors:
        return {"ok": False, "errors": errors, "warnings": warnings, "meta": meta}

    # --------- שער ראשי: gate_trade (חוסם קשיח) ---------
    g = gate_trade(
        symbol=symbol,
        side=side,
        price=price,
        entry=entry,
        sl=sl,
        tp1=tp1,
        vol_regime=DEFAULT_VOL_REGIME,
        success_pct=success_pct,
        leverage=lev,
    )
    if not g.get("ok", False):
        errors.extend(g.get("errors", []))
    warnings.extend(g.get("warnings", []))

    # נשמור קצת מטא מהשער הראשי אם החזיר
    for k in ("rr", "entry_gap_pct", "distance_sl_pct", "distance_tp1_pct"):
        if k in g:
            meta[k] = g[k]

    # --------- בדיקות רכות משלימות (warnings בלבד) ---------
    # 1) RR בסיסי מה־levels – הצגת אזהרה אם נמוך מסף ידידותי
    try:
        # NOTE: rr_from_levels(entry, sl, tp1) — אינו תלוי side (יחס מוחלט של Reward/Risk)
        rr_val = rr_from_levels(entry, sl, tp1)
        meta["rr_basic"] = rr_val
        if rr_val is not None and rr_val < RR_WARN_THRESHOLD:
            warnings.append(f"RR is modest (~{rr_val:.2f} < {RR_WARN_THRESHOLD:.2f})")
    except Exception:
        # לא נכשיל על חישוב RR משני
        pass

    # 2) מרחק כניסה מהמחיר הנוכחי – אם יש price
    if price is not None and price > 0 and entry is not None:
        try:
            # entry_gap_ok(price, entry [, max_gap_pct]) → bool
            eg_ok = entry_gap_ok(price, entry, ENTRY_GAP_MAX_PCT)
            eg_pct = abs(entry - price) / price * 100.0
            meta["entry_gap_pct_local"] = eg_pct
            if eg_ok:
                if eg_pct > ENTRY_GAP_WARN_PCT:
                    warnings.append(f"entry somewhat far from current (~{eg_pct:.2f}%)")
            else:
                # לא חוסם כאן; gate_trade כבר קבע אם זה חמור
                warnings.append(f"entry far from current (~{eg_pct:.2f}%)")
        except Exception:
            pass

        # 3) סטופ צמוד מדי למחיר הנוכחי (רק אינדיקטור)
        try:
            stop_gap_pct = abs(entry - sl) / price * 100.0 if sl is not None else None
            if stop_gap_pct is not None:
                meta["stop_gap_pct"] = stop_gap_pct
                if stop_gap_pct < 0.15:
                    warnings.append(f"stop very tight (~{stop_gap_pct:.3f}%)")
        except Exception:
            pass

    # --------- פלט ---------
    return {
        "ok": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "meta": {
            "symbol": symbol,
            "side": side,
            "entry": entry,
            "sl": sl,
            "tp1": tp1,
            **meta,
        },
    }




