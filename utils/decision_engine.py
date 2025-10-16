# utils/decision_engine.py
from __future__ import annotations
import logging, os
from typing import Dict, Any, Optional, List
from collections import defaultdict

logger = logging.getLogger("algogpt.decision")

try:
    from utils.ai_analysis import analyze_with_ai  # type: ignore
except Exception as _e:
    logger.warning("utils.ai_analysis.analyze_with_ai not available: %s (using fallback)", _e)
    async def analyze_with_ai(payload: Dict[str, Any]) -> Dict[str, Any]:  # type: ignore
        return {"ok": False, "reason": "ai_module_missing"}

def _to_float(s: Optional[str], default: float) -> float:
    try: return float(s) if s is not None else default
    except Exception: return default

QUALITY_WEIGHT       = _to_float(os.getenv("QUALITY_WEIGHT"),       0.45)
ABC_LOCAL_WEIGHT     = _to_float(os.getenv("ABC_LOCAL_WEIGHT"),     0.25)
SR_LEVELS_WEIGHT     = _to_float(os.getenv("SR_LEVELS_WEIGHT"),     0.15)
EXTERNAL_TV_WEIGHT   = _to_float(os.getenv("EXTERNAL_TV_WEIGHT"),   0.15)
FINAL_PROB_MIN       = _to_float(os.getenv("FINAL_PROB_MIN"),       0.60)

ABC_LOCAL_ENABLE     = str(os.getenv("ABC_LOCAL_ENABLE", "1")).lower() in ("1","true","yes","on")
SR_LEVELS_ENABLE     = str(os.getenv("SR_LEVELS_ENABLE", "1")).lower() in ("1","true","yes","on")
TV_ENABLE            = str(os.getenv("TV_ENABLE", "0")).lower()      in ("1","true","yes","on")

LEGACY_QUALITY_PASS  = _to_float(os.getenv("QUALITY_MIN_SCORE"), 8.5)

def _clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else (1.0 if x > 1.0 else x)

def _normalize_score(x: Optional[float]) -> Optional[float]:
    if x is None: return None
    try: v = float(x)
    except Exception: return None
    if 0.0 <= v <= 1.0: return v
    if 1.0 < v <= 10.0: return _clamp01(v / 10.0)
    if 10.0 < v <= 100.0: return _clamp01(v / 100.0)
    return _clamp01(v)

def _safe_get_float(d: Dict[str, Any], key: str) -> Optional[float]:
    try:
        if d.get(key) is None: return None
        return float(d.get(key))
    except Exception:
        return None

async def make_decision(features: Dict[str, Any], quality_score: float) -> Dict[str, Any]:
    symbol = str(features.get("symbol") or "UNKNOWN").upper()
    side   = str(features.get("side") or "LONG").upper()

    entry = _safe_get_float(features, "entry")
    sl    = _safe_get_float(features, "sl")
    tp1   = _safe_get_float(features, "tp1")

    anchor_ok = bool(features.get("anchor_ok", True))
    risk_ok   = bool(features.get("risk_ok",   True))

    qn  = _normalize_score(quality_score)
    abn = _normalize_score(_safe_get_float(features, "abc_score"))
    srn = _normalize_score(_safe_get_float(features, "sr_score"))
    tvn = _normalize_score(_safe_get_float(features, "tv_score"))

    weights: Dict[str, float] = {}
    scores:  Dict[str, Optional[float]] = {}

    weights["quality"] = QUALITY_WEIGHT
    scores["quality"]  = qn

    if ABC_LOCAL_ENABLE and abn is not None:
        weights["abc_local"] = ABC_LOCAL_WEIGHT
        scores["abc_local"]  = abn

    if SR_LEVELS_ENABLE and srn is not None:
        weights["sr_levels"] = SR_LEVELS_WEIGHT
        scores["sr_levels"]  = srn

    if TV_ENABLE and tvn is not None:
        weights["external_tv"] = EXTERNAL_TV_WEIGHT
        scores["external_tv"]  = tvn

    num = 0.0; den = 0.0
    for k, w in weights.items():
        sc = scores.get(k)
        if sc is None: continue
        num += w * sc; den += w
    final_prob = _clamp01(num / den) if den > 0 else (qn if qn is not None else 0.0)

    approved_prob = final_prob >= FINAL_PROB_MIN
    legacy_ok = (quality_score >= LEGACY_QUALITY_PASS)

    veto: Optional[str] = None
    if not anchor_ok: veto = "anchor"
    elif not risk_ok: veto = "risk"

    approved = (approved_prob or legacy_ok) and (veto is None)

    ai_summary = ""
    try:
        ai_res = await analyze_with_ai({
            **features, "final_prob": final_prob, "approved_prob": approved_prob, "veto": veto or "",
        })
        if ai_res.get("ok"):
            ai_summary = ai_res.get("analysis", "") or ai_res.get("summary", "") or ""
            if not ai_summary:
                ai_summary = f"[AI ok] {symbol} {side} prob={final_prob:.2f} entry={entry}, SL={sl}, TP1={tp1}"
        else:
            ai_summary = f"[Fallback] {symbol} {side} prob={final_prob:.2f} entry={entry}, SL={sl}, TP1={tp1}"
    except Exception as e:
        logger.error("AI analysis failed: %s", e)
        ai_summary = f"[AI error → fallback] {symbol} {side} {final_prob:.2f} | entry={entry}, SL={sl}, TP1={tp1}"

    reasons: List[str] = []
    if qn is not None: reasons.append(f"Quality={qn:.2f}*{QUALITY_WEIGHT:.2f}")
    if "abc_local" in scores and scores["abc_local"] is not None:
        reasons.append(f"ABC={scores['abc_local']:.2f}*{ABC_LOCAL_WEIGHT:.2f}")
    if "sr_levels" in scores and scores["sr_levels"] is not None:
        reasons.append(f"SR={scores['sr_levels']:.2f}*{SR_LEVELS_WEIGHT:.2f}")
    if "external_tv" in scores and scores["external_tv"] is not None:
        reasons.append(f"TV={scores['external_tv']:.2f}*{EXTERNAL_TV_WEIGHT:.2f}")
    if veto: reasons.append(f"VETO={veto}")

    return {
        "symbol": symbol, "side": side, "approved": bool(approved), "veto": veto,
        "quality_score": quality_score, "final_prob": final_prob, "approved_prob": approved_prob,
        "thresholds": {"FINAL_PROB_MIN": FINAL_PROB_MIN, "LEGACY_QUALITY_PASS": LEGACY_QUALITY_PASS},
        "weights": weights, "scores": scores, "ai_summary": ai_summary, "reasons": reasons,
        "entry": entry, "sl": sl, "tp1": tp1,
    }

def _num(x: Any, default=0.0) -> float:
    try: return float(x)
    except Exception: return float(default)

def select_best_trades(
    candidates: List[Dict[str, Any]], top_n: int = 5, diversify_by_symbol: bool = True,
    weights: Dict[str, float] | None = None,
) -> List[Dict[str, Any]]:
    if not candidates: return []
    w = { "quality":0.45, "speed":0.20, "momentum":0.15, "confidence":0.10, "risk":0.10 }
    if weights:
        try: w.update({k: float(v) for k, v in weights.items()})
        except Exception as e: logger.warning("weights override invalid: %s (using defaults)", e)

    scored: List[Dict[str, Any]] = []
    for c in candidates:
        if "_score" in c: base = _num(c.get("_score"))
        elif "score" in c: base = _num(c.get("score"))
        elif "final_prob" in c: base = _num(c.get("final_prob"))
        else:
            base = (w["quality"]*_num(c.get("quality")) +
                    w["speed"]*_num(c.get("speed")) +
                    w["momentum"]*_num(c.get("momentum")) +
                    w["confidence"]*_num(c.get("confidence")) -
                    w["risk"]*_num(c.get("risk")))
        out = dict(c); out["_score"] = float(base); scored.append(out)

    scored.sort(key=lambda x: x.get("_score", 0.0), reverse=True)
    if not diversify_by_symbol:
        return scored[:max(0, int(top_n))]

    buckets: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for item in scored:
        sym = str(item.get("symbol") or item.get("pair") or "").upper()
        buckets[sym].append(item)

    picked: List[Dict[str, Any]] = []
    while len(picked) < max(0, int(top_n)):
        advanced = False
        for sym, arr in list(buckets.items()):
            if arr and len(picked) < top_n:
                picked.append(arr.pop(0)); advanced = True
        if not advanced: break
    return picked[:top_n]

__all__ = ["make_decision", "select_best_trades"]










