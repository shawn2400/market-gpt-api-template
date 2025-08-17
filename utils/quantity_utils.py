# utils/quality.py
from __future__ import annotations
import json
import math
import os
from typing import Optional, Dict, Any, Literal, Tuple
from utils.anchor import AnchorDecision

Side = Literal["LONG", "SHORT"]

def _safe_load_history(path: str) -> list[dict]:
    try:
        if not os.path.isfile(path):
            return []
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []

def _empirical_win_rate(history: list[dict], symbol: str, side: Side, limit: int = 200) -> Optional[float]:
    """WinRate אמפירי אחרונים לפי סימבול+כיוון אם קיים לוג."""
    if not history:
        return None
    rows = [r for r in history if str(r.get("symbol","")).upper()==symbol.upper() and r.get("side")==side]
    rows = rows[-limit:] if len(rows) > limit else rows
    if not rows:
        return None
    wins = 0
    total = 0
    for r in rows:
        status = r.get("status") or r.get("result",{}).get("status")
        pnl = r.get("pnl") or r.get("result",{}).get("pnl")
        if status is not None:
            total += 1
            if str(status).lower() in {"win", "success", "closed_tp", "tp"} or (isinstance(pnl,(int,float)) and pnl>0):
                wins += 1
    if total == 0:
        return None
    return wins / total

def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))

def compute_quality(
    *,
    symbol: str,
    side: Side,
    entry: Optional[float],
    sl: Optional[float],
    tp: Optional[float],
    leverage: int,
    budget: float,
    anchor: AnchorDecision,
    atr: Optional[float] = None,
    trades_log_path: str = None,
) -> Dict[str, Any]:
    """
    מחזיר:
    - quality_score: 0-10
    - success_pct: 0-100
    - components: נימוקים
    """
    components: Dict[str, Any] = {}
    score = 5.0  # בסיס

    # יחס סיכוי/סיכון (R:R)
    rr = None
    if entry and sl and tp:
        risk = abs(entry - sl)
        reward = abs(tp - entry)
        rr = (reward / risk) if risk > 0 else None
        if rr is not None:
            if rr >= 2.0:
                score += 2.0
            elif rr >= 1.5:
                score += 1.0
            elif rr < 1.0:
                score -= 1.0
    components["rr"] = rr

    # מינוף
    if leverage <= 10:
        score += 0.5
    elif leverage >= 30:
        score -= 0.8
    components["leverage"] = leverage

    # ATR מול סטופ (אם קיים) – עצבנות שוק
    if atr and entry and sl:
        stop_dist = abs(entry - sl)
        atr_mult = (stop_dist / atr) if atr > 0 else None
        components["atr_mult"] = atr_mult
        if atr_mult is not None:
            if atr_mult < 1.0:
                score -= 0.7   # סטופ צפוף מהתנודתיות
            elif atr_mult >= 1.5:
                score += 0.3

    # עוגן BTC
    if anchor.bias == "neutral":
        score += 0.0
    else:
        aligned = (side == "LONG" and anchor.bias == "bull") or (side == "SHORT" and anchor.bias == "bear")
        if aligned:
            # חיזוק: עד +1.2 לפי עוצמה
            bonus = min(1.2, max(0.2, anchor.score / 100.0 * 1.2))
            score += bonus
            components["anchor_alignment"] = f"aligned(+{bonus:.2f})"
        else:
            # ענישה: עד -1.8 לפי עוצמה
            penalty = min(1.8, max(0.4, anchor.score / 100.0 * 1.8))
            score -= penalty
            components["anchor_alignment"] = f"conflict(-{penalty:.2f})"
    components["anchor"] = {"bias": anchor.bias, "score": anchor.score, "mode": anchor.mode_applied}

    # תקציב
    if budget > 0 and entry:
        # אפשר להוסיף בדיקות של גודל פוזיציה מול נזילות – נשאיר ניטרלי כרגע
        pass

    # גבולות
    score = max(0.0, min(10.0, score))
    components["raw_score"] = score

    # המרה להסתברות “הנדסית”: 0-100
    # ממפים סביב 5 כ-50%, 10 → ~90% , 0 → ~10%
    x = (score - 5.0) / 1.6
    p_model = _sigmoid(x)
    success_pct_model = p_model * 100.0

    # שילוב אמפירי אם יש היסטוריה
    if trades_log_path is None:
        trades_log_path = os.getenv("TRADES_LOG_PATH", "data/trades_log.json")
    hist = _safe_load_history(trades_log_path)
    wr = _empirical_win_rate(hist, symbol, side, limit=200)
    components["emp_win_rate"] = wr

    if wr is not None:
        # בלנד 60% אמפירי, 40% מודל
        success_pct = 100.0 * (0.6 * wr + 0.4 * (success_pct_model / 100.0))
        # כוונון קל של score למעלה/מטה לפי אמפירי
        score += (wr - 0.5) * 2.0  # +/-1 לכל 50% סטייה
        score = max(0.0, min(10.0, score))
        components["blend"] = "empirical(0.6)+model(0.4)"
    else:
        success_pct = success_pct_model
        components["blend"] = "model_only"

    return {
        "quality_score": round(score, 2),
        "success_pct": round(success_pct, 1),
        "components": components,
    }











