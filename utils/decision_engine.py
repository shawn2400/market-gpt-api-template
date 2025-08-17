# utils/decision_engine.py
from __future__ import annotations
from typing import List, Dict, Any

def pick_best_trades(candidates: List[Dict[str, Any]], top_n: int = 5, diversify_by_symbol: bool = True) -> Dict[str, Any]:
    """
    ניקוד רב-קריטריוני:
      base = 0.55*quality + 0.20*success + 0.10*(1 - corr_pen) + 0.15*speed_bonus
      corr_pen = max(0, |corr_to_btc| - 0.7) / 0.3  (מעבר ל-0.7 מקבלים קנס עד 1)
      speed_bonus = clamp( (180 - eta)/180, 0..1 )  (ETA קצר יותר = עדיפות)
    """
    def _clamp(x, a, b): return max(a, min(b, x))
    scored = []
    for c in candidates or []:
        q = float(c.get("quality_score") or 0.0) / 10.0  # → 0..1
        s = float(c.get("success_pct") or 0.0) / 100.0   # → 0..1
        corr = abs(float(c.get("corr_to_btc") or 0.0))
        eta = float(c.get("eta_minutes") or 120.0)
        corr_pen = _clamp((corr - 0.7) / 0.3, 0.0, 1.0)
        speed_bonus = _clamp((180.0 - eta) / 180.0, 0.0, 1.0)
        score = 0.55*q + 0.20*s + 0.10*(1.0 - corr_pen) + 0.15*speed_bonus
        scored.append({**c, "decision_score": round(score, 4)})
    scored.sort(key=lambda x: x["decision_score"], reverse=True)

    if diversify_by_symbol:
        seen = set()
        dedup = []
        for it in scored:
            sym = (it.get("symbol") or "").upper()
            if sym in seen: 
                continue
            seen.add(sym)
            dedup.append(it)
        scored = dedup

    return {"ok": True, "selected": scored[:max(1, int(top_n))], "note": "Decision by multi-criteria score"}

