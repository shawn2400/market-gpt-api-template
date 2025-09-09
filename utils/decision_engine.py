# utils/decision_engine.py
from __future__ import annotations
import logging, os
from typing import Dict, Any, Optional, List
from collections import defaultdict

logger = logging.getLogger("algogpt.decision")

# --- Optional AI analysis import (non-fatal fallback) ---
try:
    from utils.ai_analysis import analyze_with_ai  # type: ignore
except Exception as _e:
    logger.warning("utils.ai_analysis.analyze_with_ai not available: %s (using fallback)", _e)

    async def analyze_with_ai(payload: Dict[str, Any]) -> Dict[str, Any]:  # type: ignore
        # Fallback: non-blocking, returns "not ok"
        return {"ok": False, "reason": "ai_module_missing"}

# =========================
# ENV Weights / Thresholds
# =========================
def _to_float(s: Optional[str], default: float) -> float:
    try:
        return float(s) if s is not None else default
    except Exception:
        return default

QUALITY_WEIGHT       = _to_float(os.getenv("QUALITY_WEIGHT"),       0.45)
ABC_LOCAL_WEIGHT     = _to_float(os.getenv("ABC_LOCAL_WEIGHT"),     0.25)
SR_LEVELS_WEIGHT     = _to_float(os.getenv("SR_LEVELS_WEIGHT"),     0.15)
EXTERNAL_TV_WEIGHT   = _to_float(os.getenv("EXTERNAL_TV_WEIGHT"),   0.15)
FINAL_PROB_MIN       = _to_float(os.getenv("FINAL_PROB_MIN"),       0.60)

ABC_LOCAL_ENABLE     = str(os.getenv("ABC_LOCAL_ENABLE", "1")).lower() in ("1","true","yes","on")
SR_LEVELS_ENABLE     = str(os.getenv("SR_LEVELS_ENABLE", "1")).lower() in ("1","true","yes","on")
TV_ENABLE            = str(os.getenv("TV_ENABLE", "0")).lower()      in ("1","true","yes","on")

# שמירה על תאימות אחורה — סף ישן של 8.5 (אם משתמשים רק ב-quality)
LEGACY_QUALITY_PASS  = _to_float(os.getenv("QUALITY_MIN_SCORE"), 8.5)  # ← נשאר 8.5 כפי שביקשת

def _clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else (1.0 if x > 1.0 else x)

def _normalize_score(x: Optional[float]) -> Optional[float]:
    """
    מנרמל ציון ל-[0..1].
      - אם כבר הסתברות [0..1] → נשאר.
      - אם 0..10 → /10 (למשל 8.5 -> 0.85)
      - אם 0..100 → /100
    """
    if x is None:
        return None
    try:
        v = float(x)
    except Exception:
        return None
    if 0.0 <= v <= 1.0:
        return v
    if 1.0 < v <= 10.0:
        return _clamp01(v / 10.0)
    if 10.0 < v <= 100.0:
        return _clamp01(v / 100.0)
    # מחוץ לטווחים רגילים — נחתוך
    return _clamp01(v)

def _safe_get_float(d: Dict[str, Any], key: str) -> Optional[float]:
    try:
        if d.get(key) is None:
            return None
        return float(d.get(key))
    except Exception:
        return None

# =========================
# Decision (single trade)
# =========================
async def make_decision(features: Dict[str, Any], quality_score: float) -> Dict[str, Any]:
    """
    מחליט אם לבצע טרייד או לא, עם תמיכה בשקלול מודולים אופציונליים:
      - quality_score (חובה לפונקציה; 0..10/100/1)
      - features.abc_score        (0..1 או 0..10/100)
      - features.sr_score         (0..1 או 0..10/100)
      - features.tv_score         (0..1 או 0..10/100) — אם הגיע hook חיצוני
      - features.anchor_ok        (bool) — וטו עוגן (BTC/ETH)
      - features.risk_ok          (bool) — וטו ניהול סיכונים
      - שדות אופציונליים (entry/sl/tp1...) עבור תקציר AI

    תאימות אחורה:
      - אם אין ABC/SR/TV/Anchor/Risk → משתמש רק ב-quality כפי שהיה.
    """
    symbol = str(features.get("symbol") or "UNKNOWN").upper()
    side   = str(features.get("side") or "LONG").upper()

    entry = _safe_get_float(features, "entry")
    sl    = _safe_get_float(features, "sl")
    tp1   = _safe_get_float(features, "tp1")

    # Gates (רשות): אם לא סופקו — True
    anchor_ok = bool(features.get("anchor_ok", True))
    risk_ok   = bool(features.get("risk_ok",   True))

    # נרמול ציונים
    qn  = _normalize_score(quality_score)
    abn = _normalize_score(_safe_get_float(features, "abc_score"))
    srn = _normalize_score(_safe_get_float(features, "sr_score"))
    tvn = _normalize_score(_safe_get_float(features, "tv_score"))

    # בניית משקולות פעילות בלבד (רק מה שיש + מופעל ב-ENV)
    weights: Dict[str, float] = {}
    scores:  Dict[str, Optional[float]] = {}

    # Quality תמיד קיים
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

    # חישוב הסתברות סופית משוקללת
    num = 0.0
    den = 0.0
    for k, w in weights.items():
        sc = scores.get(k)
        if sc is None:
            continue
        num += w * sc
        den += w
    final_prob = _clamp01(num / den) if den > 0 else (qn if qn is not None else 0.0)

    # ספי החלטה
    approved_prob = final_prob >= FINAL_PROB_MIN

    # תאימות אחורה — אם אין מודולים נוספים (רק quality), כבדיקת גיבוי
    legacy_ok = (quality_score >= LEGACY_QUALITY_PASS)

    # VETO לוגי
    veto: Optional[str] = None
    if not anchor_ok:
        veto = "anchor"
    elif not risk_ok:
        veto = "risk"

    # החלטה סופית: חייב לעבור סף AND ללא וטו
    approved = (approved_prob or legacy_ok) and (veto is None)

    # ניתוח GPT (לא חוסם)
    ai_summary = ""
    try:
        ai_res = await analyze_with_ai({
            **features,
            "final_prob": final_prob,
            "approved_prob": approved_prob,
            "veto": veto or "",
        })
        if ai_res.get("ok"):
            ai_summary = ai_res.get("analysis", "") or ai_res.get("summary", "")
            if not ai_summary:
                ai_summary = (
                    f"[AI ok] {symbol} {side} "
                    f"prob={final_prob:.2f} q={qn if qn is not None else 'NA'} "
                    f"entry={entry}, SL={sl}, TP1={tp1}"
                )
        else:
            ai_summary = (
                f"[Fallback] {symbol} {side} "
                f"prob={final_prob:.2f} (q={qn if qn is not None else 'NA'}) "
                f"entry={entry}, SL={sl}, TP1={tp1}"
            )
    except Exception as e:
        logger.error("AI analysis failed: %s", e)
        ai_summary = (
            f"[AI error → fallback] {symbol} {side} "
            f"{final_prob:.2f} | entry={entry}, SL={sl}, TP1={tp1}"
        )

    # Reasons / פירוק החלטה
    reasons: List[str] = []
    if qn is not None:
        reasons.append(f"Quality={qn:.2f}*{QUALITY_WEIGHT:.2f}")
    if "abc_local" in scores and scores["abc_local"] is not None:
        reasons.append(f"ABC={scores['abc_local']:.2f}*{ABC_LOCAL_WEIGHT:.2f}")
    if "sr_levels" in scores and scores["sr_levels"] is not None:
        reasons.append(f"SR={scores['sr_levels']:.2f}*{SR_LEVELS_WEIGHT:.2f}")
    if "external_tv" in scores and scores["external_tv"] is not None:
        reasons.append(f"TV={scores['external_tv']:.2f}*{EXTERNAL_TV_WEIGHT:.2f}")
    if veto:
        reasons.append(f"VETO={veto}")

    decision: Dict[str, Any] = {
        "symbol": symbol,
        "side": side,
        "approved": bool(approved),
        "veto": veto,  # 'anchor' / 'risk' / None
        "quality_score": quality_score,
        "final_prob": final_prob,
        "approved_prob": approved_prob,
        "thresholds": {
            "FINAL_PROB_MIN": FINAL_PROB_MIN,
            "LEGACY_QUALITY_PASS": LEGACY_QUALITY_PASS,
        },
        "weights": weights,
        "scores": scores,
        "ai_summary": ai_summary,
        "reasons": reasons,
        # מידע אופציונלי ל־execution/bot
        "entry": entry,
        "sl": sl,
        "tp1": tp1,
    }
    return decision

# =========================
# Selection (many trades)
# =========================
def _num(x: Any, default=0.0) -> float:
    try:
        return float(x)
    except Exception:
        return float(default)

def select_best_trades(
    candidates: List[Dict[str, Any]],
    top_n: int = 5,
    diversify_by_symbol: bool = True,
    weights: Dict[str, float] | None = None,
) -> List[Dict[str, Any]]:
    """
    בוחר עסקאות מובילות על בסיס ציון משוקלל ואפשרות לדיברסיפיקציה לפי סמל.

    שדות נתמכים (גמיש; לא חובה הכול):
      - _score / score / final_prob / quality_score / quality / speed / momentum / confidence / risk
      - symbol / pair (לצורך דיברסיפיקציה)
    """
    if not candidates:
        return []

    # ברירת מחדל משקולות (ניתן לדרוס בפרמטר weights)
    w = {
        "quality":   0.45,
        "speed":     0.20,
        "momentum":  0.15,
        "confidence":0.10,
        "risk":      0.10,  # יורד מהציון
    }
    if weights:
        try:
            w.update({k: float(v) for k, v in weights.items()})
        except Exception as e:
            logger.warning("weights override invalid: %s (using defaults)", e)

    scored: List[Dict[str, Any]] = []

    for c in candidates:
        # אם כבר יש _score / score / final_prob — נכבד
        if "_score" in c:
            base_score = _num(c.get("_score"))
        elif "score" in c:
            base_score = _num(c.get("score"))
        elif "final_prob" in c:
            base_score = _num(c.get("final_prob"))  # מניח 0..1
        else:
            # נחשב מסקאלרים סטנדרטיים (0..10) ונחסר סיכון
            q  = _num(c.get("quality"))
            sp = _num(c.get("speed"))
            mo = _num(c.get("momentum"))
            cf = _num(c.get("confidence"))
            rk = _num(c.get("risk"))
            base_score = (
                w["quality"]*q +
                w["speed"]*sp +
                w["momentum"]*mo +
                w["confidence"]*cf -
                w["risk"]*rk
            )

        out = dict(c)
        out["_score"] = float(base_score)
        scored.append(out)

    # מיון לפי ציון יורד
    scored.sort(key=lambda x: x.get("_score", 0.0), reverse=True)

    if not diversify_by_symbol:
        return scored[:max(0, int(top_n))]

    # דיברסיפיקציה לפי סמלים (round-robin)
    buckets: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for item in scored:
        sym = str(item.get("symbol") or item.get("pair") or "").upper()
        buckets[sym].append(item)

    picked: List[Dict[str, Any]] = []
    while len(picked) < max(0, int(top_n)):
        advanced = False
        for sym, arr in list(buckets.items()):
            if arr and len(picked) < top_n:
                picked.append(arr.pop(0))
                advanced = True
        if not advanced:
            break

    return picked[:top_n]

__all__ = ["make_decision", "select_best_trades"]










