# utils/quality.py
from __future__ import annotations
import json, math, os
from typing import Optional, Dict, Any, Literal
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
    if not history:
        return None
    rows = [r for r in history if str(r.get("symbol","")).upper()==symbol.upper() and r.get("side")==side]
    rows = rows[-limit:] if len(rows) > limit else rows
    if not rows:
        return None
    wins = 0
    total = 0
    for r in rows:
        status = (r.get("status") or r.get("result",{}).get("status") or "").lower()
        pnl = r.get("pnl") or r.get("result",{}).get("pnl")
        if status:
            total += 1
            if status in {"win","success","closed_tp","tp"} or (isinstance(pnl,(int,float)) and pnl>0):
                wins += 1
    if total == 0:
        return None
    return wins/total

def _sigmoid(x: float) -> float:
    return 1.0/(1.0+math.exp(-x))

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
    components: Dict[str, Any] = {}
    score = 5.0

    rr = None
    if entry and sl and tp:
        risk = abs(entry - sl)
        reward = abs(tp - entry)
        rr = (reward / risk) if risk > 0 else None
        if rr is not None:
            if rr >= 2.0: score += 2.0
            elif rr >= 1.5: score += 1.0
            elif rr < 1.0: score -= 1.0
    components["rr"] = rr

    if leverage <= 10: score += 0.5
    elif leverage >= 30: score -= 0.8
    components["leverage"] = leverage

    if atr and entry and sl:
        stop_dist = abs(entry - sl)
        atr_mult = (stop_dist / atr) if atr > 0 else None
        components["atr_mult"] = atr_mult
        if atr_mult is not None:
            if atr_mult < 1.0: score -= 0.7
            elif atr_mult >= 1.5: score += 0.3

    if anchor.bias == "neutral":
        pass
    else:
        aligned = (side=="LONG" and anchor.bias=="bull") or (side=="SHORT" and anchor.bias=="bear")
        if aligned:
            bonus = min(1.2, max(0.2, anchor.score/100.0*1.2))
            score += bonus
            components["anchor_alignment"] = f"aligned(+{bonus:.2f})"
        else:
            penalty = min(1.8, max(0.4, anchor.score/100.0*1.8))
            score -= penalty
            components["anchor_alignment"] = f"conflict(-{penalty:.2f})"
    components["anchor"] = {"bias": anchor.bias, "score": anchor.score, "mode": anchor.mode_applied}

    score = max(0.0, min(10.0, score))
    components["raw_score"] = score

    x = (score - 5.0) / 1.6
    p_model = _sigmoid(x)
    success_pct_model = p_model * 100.0

    if trades_log_path is None:
        trades_log_path = os.getenv("TRADES_LOG_PATH", "data/trades_log.json")
    hist = _safe_load_history(trades_log_path)
    wr = _empirical_win_rate(hist, symbol, side, limit=200)
    components["emp_win_rate"] = wr

    if wr is not None:
        success_pct = 100.0 * (0.6*wr + 0.4*(success_pct_model/100.0))
        score += (wr - 0.5) * 2.0
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

















