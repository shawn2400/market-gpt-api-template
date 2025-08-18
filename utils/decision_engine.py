# utils/decision_engine.py
from __future__ import annotations
from typing import List, Dict, Any
from utils.scoring import decision_score, weights_norm

def _components_from_candidate(c: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "quality": float(c.get("quality_score", c.get("quality", 0.0))),
        "success_pct": c.get("success_pct"),
        "eta_minutes": c.get("eta_minutes"),
        "volatility": c.get("volatility"),
        "corr_to_btc": c.get("corr_to_btc"),
    }

def select_best_trades(
    candidates: List[Dict[str, Any]],
    top_n: int = 5,
    diversify_by_symbol: bool = True,
) -> List[Dict[str, Any]]:
    enriched: List[Dict[str, Any]] = []
    for c in (candidates or []):
        comps = _components_from_candidate(c)
        score = decision_score(comps)
        enriched.append({
            "symbol": str(c.get("symbol", "")).upper(),
            "side": c.get("side"),
            "score": score,
            "components": {
                "quality": comps["quality"],
                "success_pct": comps["success_pct"],
                "eta": comps["eta_minutes"],
                "volatility": comps["volatility"],
                "decorr": (None if comps["corr_to_btc"] is None else (1.0 - abs(float(comps["corr_to_btc"])))),
                "weights": {
                    "quality": weights_norm()[0],
                    "success": weights_norm()[1],
                    "eta": weights_norm()[2],
                    "volatility": weights_norm()[3],
                    "decorr": weights_norm()[4],
                }
            },
            "raw": c,
        })

    enriched.sort(key=lambda x: x["score"], reverse=True)

    if diversify_by_symbol:
        seen = set()
        filtered = []
        for it in enriched:
            sym = it["symbol"]
            if sym in seen:
                continue
            seen.add(sym)
            filtered.append(it)
        enriched = filtered

    enriched = enriched[: int(top_n)]
    for i, it in enumerate(enriched, 1):
        it["rank"] = i
    return enriched







