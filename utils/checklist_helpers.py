# utils/checklist_helpers.py
from __future__ import annotations
import os
from typing import Dict, Any, List, Tuple
from utils.pretrade_checklist import compute_pretrade_score

def _wilder_smooth(values: List[float], period: int) -> List[float]:
    if not values or period <= 0 or len(values) < period: return []
    smoothed = [sum(values[:period]) / period]
    for v in values[period:]:
        smoothed.append((smoothed[-1] * (period - 1) + v) / period)
    return smoothed

def indicators_from_klines(klines: List[List[Any]], period: int = 14) -> Dict[str, float]:
    try:
        highs = [float(k[2]) for k in klines]
        lows  = [float(k[3]) for k in klines]
        closes= [float(k[4]) for k in klines]
        if len(closes) < period + 2:
            return {"atr_pct": 0.0, "adx": 0.0, "price": closes[-1] if closes else 0.0}
        trs, plus_dm, minus_dm = [], [], []
        for i in range(1, len(closes)):
            h, l, ph, pl, pc = highs[i], lows[i], highs[i-1], lows[i-1], closes[i-1]
            tr = max(h - l, abs(h - pc), abs(l - pc)); trs.append(tr)
            up_move = h - ph; down_move = pl - l
            plus_dm.append(up_move if (up_move > down_move and up_move > 0) else 0.0)
            minus_dm.append(down_move if (down_move > up_move and down_move > 0) else 0.0)
        atr_series = _wilder_smooth(trs, period)
        if not atr_series: return {"atr_pct": 0.0, "adx": 0.0, "price": closes[-1]}
        atr = atr_series[-1]
        plus_di = [(p / atr_series[i]) * 100 if atr_series[i] > 0 else 0.0 for i, p in enumerate(_wilder_smooth(plus_dm, period))]
        minus_di= [(m / atr_series[i]) * 100 if atr_series[i] > 0 else 0.0 for i, m in enumerate(_wilder_smooth(minus_dm, period))]
        dx = []
        for i in range(min(len(plus_di), len(minus_di))):
            s = plus_di[i] + minus_di[i]; d = abs(plus_di[i] - minus_di[i])
            dx.append((d / s) * 100 if s > 0 else 0.0)
        adx_series = _wilder_smooth(dx, period)
        adx = adx_series[-1] if adx_series else 0.0
        price = float(closes[-1]) if closes else 0.0
        atr_pct = (atr / price) * 100.0 if price > 0 else 0.0
        return {"atr_pct": float(atr_pct), "adx": float(adx), "price": price}
    except Exception:
        return {"atr_pct": 0.0, "adx": 0.0, "price": 0.0}

def eval_checklist(klines: List[List[Any]]) -> Dict[str, Any]:
    ind = indicators_from_klines(klines, period=14)
    res = compute_pretrade_score(klines, adx=ind["adx"], atr_pct=ind["atr_pct"])
    res["indicators"] = ind
    return res

def gate_allowed(score: float) -> Tuple[bool, float]:
    mode = (os.getenv("ENTRY_SCORE_MODE","log") or "log").lower()
    min_req = float(os.getenv("ENTRY_SCORE_MIN","0") or 0.0)
    if mode == "gate" and score < min_req:
        return (False, min_req)
    return (True, min_req)
