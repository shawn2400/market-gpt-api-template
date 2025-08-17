from __future__ import annotations
import os
from typing import Literal, Optional, Dict, Any

Side = Literal["LONG", "SHORT"]

# ---- helpers ----
def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))

def _env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, "").strip() or default)
    except Exception:
        return default

def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, "").strip() or default)
    except Exception:
        return default

def _safe_div(a: float, b: float) -> float:
    return a / b if (b is not None and b != 0) else 0.0

# ---- main API ----
def compute_quality(
    *,
    symbol: str,
    side: Side,
    entry: Optional[float],
    sl: Optional[float],
    tp: Optional[float],
    leverage: int,
    budget: float,
    anchor,                 # expects AnchorDecision (מה- utils/btc_anchor)
    atr: Optional[float] = None,
) -> Dict[str, Any]:
    """
    מחשב ציון איכות 0–10 ו-% הצלחה היפותטי (heuristic) ללא היסטוריה אמיתית.
    כשהיסטוריה תתחבר – מומלץ להחליף את success_pct למודל אמיתי.
    """
    max_leverage = _env_int("MAX_LEVERAGE", 35)
    max_budget   = _env_float("MAX_TRADE_BUDGET", 100.0)

    # ברירת מחדל בטוחה אם חסר מידע (לא אמור לקרות ב-/execute אחרי הוולידציות)
    if entry is None or sl is None or tp is None:
        return {
            "quality_score": 5.0,   # ניטרלי
            "success_pct": 50.0,
            "components": {
                "note": "missing pricing inputs; returned neutral scores",
            },
        }

    # ---- 1) Risk/Reward ----
    if side == "LONG":
        risk    = max(0.0, entry - sl)
        reward  = max(0.0, tp - entry)
    else:  # SHORT
        risk    = max(0.0, sl - entry)
        reward  = max(0.0, entry - tp)

    rr = _safe_div(reward, risk) if risk > 0 else 0.0
    # נרמל ל-0..100 (RR=2 -> 100, RR=1 -> 50, RR<=0 -> 0)
    rr_score_100 = _clamp((rr / 2.0) * 100.0, 0.0, 100.0)

    # ---- 2) Leverage penalty ----
    # מעל מינוף 5 מתחיל עונש, שמגיע עד ~30 נק' ב-100% עומס לעומת המקס
    lev_ref = max(5, min(max_leverage, 125))
    lev_norm = _clamp((leverage - 5) / max(1, (lev_ref - 5)), 0.0, 1.0)
    leverage_penalty_100 = 30.0 * lev_norm  # 0..30-

    # ---- 3) ATR fit (אם קיים) ----
    atr_score_100 = 50.0  # ניטרלי אם אין ATR
    atr_mult = None
    if atr and atr > 0:
        sl_dist = abs(entry - sl)
        atr_mult = _safe_div(sl_dist, atr)  # כמה ATR יש עד ה-SL
        # sweet spot ~ 1.0–2.0 ATR ל-SL
        if atr_mult <= 0:
            atr_score_100 = 10.0
        else:
            # פונקציה "פעמון" פשוטה סביב 1.5 ATR, רוחב ~1.5
            atr_score_100 = 100.0 - _clamp(abs(atr_mult - 1.5) / 1.5 * 40.0, 0.0, 40.0)  # 60..100
    # clamp סופי
    atr_score_100 = _clamp(atr_score_100, 0.0, 100.0)

    # ---- 4) Anchor adjustment ----
    # יישום רך: ב-align מוסיף עד +20; ב-conflict חלש מפחית עד -25. strong נחסם upstream.
    anchor_adj_100 = 0.0
    if anchor and getattr(anchor, "bias", None):
        align = ((side == "LONG" and anchor.bias == "bull") or
                 (side == "SHORT" and anchor.bias == "bear"))
        conflict = ((side == "LONG" and anchor.bias == "bear") or
                    (side == "SHORT" and anchor.bias == "bull"))
        s = float(getattr(anchor, "score", 0.0))
        sev = getattr(anchor, "severity", "none")

        if align:
            anchor_adj_100 = _clamp(s * 0.20, 0.0, 20.0)  # עד +20
        elif conflict and sev in ("weak",):
            anchor_adj_100 = -_clamp(s * 0.25, 0.0, 25.0)  # עד -25
        else:
            anchor_adj_100 = 0.0
    # אם HARD, ה-gate כבר חסם לפני הקריאה לפונקציה הזו.

    # ---- 5) Budget sanity ----
    budget_adj_100 = 0.0
    if budget > max_budget:
        # חריגה מהתקציב המוגדר — הורדה עד 10 נק'
        over = (budget - max_budget) / max_budget
        budget_adj_100 = -_clamp(over * 10.0, 0.0, 10.0)

    # ---- 6) קומבינציה ל-0..100 ----
    # משקלים: RR 45%, ATR 20%, Anchor adj מוחל additively, מינוף מעניש, תקציב additively.
    base_100 = 0.45 * rr_score_100 + 0.20 * atr_score_100
    combined_100 = _clamp(base_100 + anchor_adj_100 + budget_adj_100 - leverage_penalty_100, 0.0, 100.0)

    # ---- 7) מיפוי לציון 0..10 ול-% הצלחה היפותטי ----
    quality_score = round(combined_100 / 10.0, 2)  # סולם 0–10 כדרישת המערכת
    # success pct heuristic: בסיס 35% + תרומה מהציון + תרומת anchor קלה - עונש מינוף
    anchor_dir = 0.0
    if anchor and getattr(anchor, "bias", None):
        if (side == "LONG" and anchor.bias == "bull") or (side == "SHORT" and anchor.bias == "bear"):
            anchor_dir = 1.0
        elif (side == "LONG" and anchor.bias == "bear") or (side == "SHORT" and anchor.bias == "bull"):
            anchor_dir = -1.0
    success_p = 0.35 \
                + 0.40 * (combined_100 / 100.0) \
                + 0.15 * anchor_dir * (_clamp(float(getattr(anchor, "score", 0.0)), 0.0, 100.0) / 100.0) \
                - 0.10 * lev_norm
    success_pct = round(_clamp(success_p, 0.05, 0.95) * 100.0, 2)

    return {
        "quality_score": quality_score,
        "success_pct": success_pct,
        "components": {
            "symbol": symbol,
            "side": side,
            "entry": entry,
            "sl": sl,
            "tp": tp,
            "risk": risk,
            "reward": reward,
            "rr": rr,
            "rr_score_100": round(rr_score_100, 2),
            "leverage": leverage,
            "max_leverage": max_leverage,
            "leverage_penalty_100": round(leverage_penalty_100, 2),
            "atr": atr,
            "sl_atr_multiple": atr_mult,
            "atr_score_100": round(atr_score_100, 2),
            "anchor_bias": getattr(anchor, "bias", None),
            "anchor_score": getattr(anchor, "score", None),
            "anchor_severity": getattr(anchor, "severity", None),
            "anchor_adj_100": round(anchor_adj_100, 2),
            "budget": budget,
            "max_budget": max_budget,
            "budget_adj_100": round(budget_adj_100, 2),
            "combined_100": round(combined_100, 2),
            "quality_scale": "0-10",
            "success_pct_note": "heuristic; replace with historical win-rate when available",
        },
    }











