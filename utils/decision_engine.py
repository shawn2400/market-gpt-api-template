# utils/decision_engine.py
from __future__ import annotations
from typing import List, Dict, Any

def select_best_trades(candidates: List[Dict[str, Any]], top_n: int = 5, diversify_by_symbol: bool = True):
    out=[]; seen=set()
    for c in sorted(candidates or [], key=lambda x: float(x.get("score", 0.0)), reverse=True):
        sym=str(c.get("symbol","")).upper()
        if diversify_by_symbol and sym in seen:
            continue
        seen.add(sym)
        out.append(c)
        if len(out) >= int(top_n):
            break
    return out







