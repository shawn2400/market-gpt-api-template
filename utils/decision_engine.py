# utils/decision_engine.py
from __future__ import annotations
from typing import List, Dict, Any, Tuple
import math

def _sym_bucket(sym: str) -> str:
    # דוגמה: "ETHUSDT" → "ETH"
    s = (sym or "").upper()
    for suf in ("USDT","USD","BUSD","USDC","PERP"):
        if s.endswith(suf):
            return s[:-len(suf)]
    return s

def _score_row(c: Dict[str, Any]) -> float:
    qs  = float(c.get("quality_score") or 0.0)  # 0..10
    sp  = float(c.get("success_pct") or 50.0)   # 0..100
    vol = float(c.get("volatility") or 0.0)     # (נורמליזציה להלן)
    eta = c.get("eta_minutes")
    corr= c.get("corr_to_btc")
    # נרמל
    sp01 = max(0.0, min(1.0, sp/100.0))
    vol01= max(0.0, min(1.0, vol/100.0))  # בהנחה שנתון באחוזי תנודתיות
    eta01= 0.5
    if isinstance(eta, (int,float)) and eta>0:
        # מהיר יותר → ציון גבוה יותר
        eta01 = max(0.0, min(1.0, 1.0 / math.log10(eta + 9.0)))
    corr01= 0.5
    if isinstance(corr, (int,float)):
        corr01 = max(0.0, min(1.0, 1.0 - abs(corr)))  # העדפה לקורלציה נמוכה עם BTC לצורך גיוון

    # שקלול
    score = (0.40 * (qs/10.0)) + (0.25 * sp01) + (0.15 * eta01) + (0.10 * vol01) + (0.10 * corr01)
    return round(score * 100.0, 2)  # 0..100

def select_best_trades(
    candidates: List[Dict[str, Any]],
    top_n: int = 5,
    diversify_by_symbol: bool = True,
) -> List[Dict[str, Any]]:
    rows = []
    for c in candidates or []:
        sc = _score_row(c)
        rows.append({**c, "score": sc})

    rows.sort(key=lambda x: x["score"], reverse=True)

    if not diversify_by_symbol:
        return rows[:top_n]

    seen = set()
    out: List[Dict[str, Any]] = []
    for r in rows:
        b = _sym_bucket(r.get("symbol",""))
        if b in seen:
            continue
        seen.add(b)
        out.append(r)
        if len(out) >= top_n:
            break
    return out


