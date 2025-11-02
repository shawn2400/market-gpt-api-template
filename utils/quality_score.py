# utils/quality_score.py
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

def _load_symbol_thresholds(symbol: str) -> Dict[str, float]:
    """
    Load per-symbol adaptive thresholds based on historical performance.
    Returns default thresholds if no history exists.
    """
    try:
        thresh_path = os.getenv("SYMBOL_THRESHOLDS_PATH", "/tmp/symbol_thresholds.json")
        if not os.path.isfile(thresh_path):
            return {"min_quality": 5.0, "min_rr": 1.3, "leverage_cap": 10}
        
        with open(thresh_path, "r", encoding="utf-8") as f:
            all_thresholds = json.load(f)
        
        return all_thresholds.get(symbol.upper(), {
            "min_quality": 5.0,
            "min_rr": 1.3,
            "leverage_cap": 10
        })
    except Exception:
        return {"min_quality": 5.0, "min_rr": 1.3, "leverage_cap": 10}

def _save_symbol_thresholds(symbol: str, thresholds: Dict[str, float]):
    """Save updated thresholds for a symbol"""
    try:
        thresh_path = os.getenv("SYMBOL_THRESHOLDS_PATH", "/tmp/symbol_thresholds.json")
        
        all_thresholds = {}
        if os.path.isfile(thresh_path):
            with open(thresh_path, "r", encoding="utf-8") as f:
                all_thresholds = json.load(f)
        
        all_thresholds[symbol.upper()] = thresholds
        
        with open(thresh_path, "w", encoding="utf-8") as f:
            json.dump(all_thresholds, f, indent=2)
    except Exception:
        pass

def update_symbol_thresholds(symbol: str, win_rate: float, avg_quality: float, total_trades: int):
    """
    Auto-adjust thresholds based on symbol performance.
    
    Args:
        symbol: Trading symbol
        win_rate: Win rate (0-1)
        avg_quality: Average quality score
        total_trades: Number of trades for statistical significance
    """
    if total_trades < 5:
        return  # Need minimum sample size
    
    current = _load_symbol_thresholds(symbol)
    
    # If win rate is high (>70%), lower thresholds to allow more trades
    if win_rate > 0.70:
        current["min_quality"] = max(4.0, current["min_quality"] - 0.2)
        current["min_rr"] = max(1.2, current["min_rr"] - 0.05)
    
    # If win rate is low (<50%), raise thresholds for better quality
    elif win_rate < 0.50:
        current["min_quality"] = min(7.0, current["min_quality"] + 0.3)
        current["min_rr"] = min(2.0, current["min_rr"] + 0.1)
    
    # Adjust leverage cap based on consistency
    if win_rate > 0.65 and avg_quality > 6.5:
        current["leverage_cap"] = min(15, current["leverage_cap"] + 1)
    elif win_rate < 0.45:
        current["leverage_cap"] = max(5, current["leverage_cap"] - 1)
    
    _save_symbol_thresholds(symbol, current)

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
    trades_log_path: Optional[str] = None,
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

















