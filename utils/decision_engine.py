# utils/decision_engine.py
from __future__ import annotations
from typing import List, Dict, Any
import math
from utils.scoring import weights_norm

def _sym_bucket(sym: str) -> str:
    s = (sym or "").upper()
    for suf in ("USDT","USD","BUSD","USDC","PERP"):
        if s.endswith(suf): return s[:-len(suf)]
    return s

def _score_row(c: Dict[str, Any]) -> float:
    w_qs, w_sp, w_eta, w_vol, w_corr = weights_norm()
    qs  = float(c.get("quality_score") or 0.0)      # 0..10
    sp  = float(c.get("success_pct") or 50.0)       # 0..100
    vol = float(c.get("volatility") or 0.0)         # 0..100 (assumed)
    eta = c.get("eta_minutes")                      # minutes
    corr= c.get("corr_to_btc")                      # -1..1 preferred near 0

    sp01  = max(0.0, min(1.0, sp/100.0))
    vol01 = max(0.0, min(1.0, vol/100.0))
    eta01 = 0.5
    if isinstance(eta, (int, float)) and eta > 0:
        eta01 = max(0.0, min(1.0, 1.0 / math.log10(eta + 9.0)))
    corr01 = 0.5
    if isinstance(corr, (int, float)):
        corr01 = max(0.0, min(1.0, 1.0 - abs(corr)))

    score01 = (w_qs * (qs/10.0)) + (w_sp * sp01) + (w_eta * eta01) + (w_vol * vol01) + (w_corr * corr01)
    return round(score01 * 100.0, 2)

def select_best_trades(
    candidates: List[Dict[str, Any]],
    top_n: int = 5,
    diversify_by_symbol: bool = True,
) -> List[Dict[str, Any]]:
    rows = [{**c, "score": _score_row(c)} for c in (candidates or [])]
    rows.sort(key=lambda x: x["score"], reverse=True)
    if not diversify_by_symbol:
        return rows[:top_n]

    seen = set(); out: List[Dict[str, Any]] = []
    for r in rows:
        b = _sym_bucket(r.get("symbol",""))
        if b in seen: 
            continue
        seen.add(b); out.append(r)
        if len(out) >= top_n: break
    return out



