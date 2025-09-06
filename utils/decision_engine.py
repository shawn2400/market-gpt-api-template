# utils/decision_engine.py
from __future__ import annotations
import logging, os
from typing import Dict, Any, Optional

from utils.ai_analysis import analyze_with_ai

logger = logging.getLogger("algogpt.decision")

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
LEGACY_QUALITY_PASS  = _to_float(os.getenv("QUALITY_MIN_SCORE"), 8.5)

def _clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else (1.0 if x > 1.0 else x)

def _normalize_score(x: Optional[float]) -> Optional[float]:
    """
    מנרמל ציון ל-[0..1].
    קלט אפשרי:
      - כבר הסתברות [0..1] → נשאר.
      - ציון 0..10 → מחלקים ב-10 (למשל 8.5 -> 0.85)
      - ציון 0..100 → מחלקים ב-100
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

async def make_decision(features: Dict[str, Any], quality_score: float) -> Dict[str, Any]:
    """
    מחליט אם לבצע טרייד או לא, עם תמיכה בשקלול מודולים אופציונליים:
      - quality_score (חובה לפונקציה; 0..10/100/1)
      - features.abc_score        (0..1 או 0..10/100)
      - features.sr_score         (0..1 או 0..10/100)
      - features.tv_score         (0..1 או 0..10/100) — אם הגיע hook חיצוני
      - features.anchor_ok        (bool) — וטו עוגן (BTC/ETH)
      - features.risk_ok          (bool) — וטו ניהול סיכונים
      - fields תפעוליים (entry/sl/tp1...) לצורך תקציר AI

    תואם אחורה:
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
            ai_summary = ai_res["analysis"]
        else:
            ai_summary = (
                f"[Fallback] {symbol} {side} "
                f"prob={final_prob:.2f} (q={qn if qn is not None else 'NA'}) "
                f"entry={entry}, SL={sl}, TP1={tp1}"
            )
    except Exception as e:
        logger.error(f"AI analysis failed: {e}")
        ai_summary = (
            f"[AI error → fallback] {symbol} {side} "
            f"{final_prob:.2f} | entry={entry}, SL={sl}, TP1={tp1}"
        )

    # Reasons / פירוק החלטה
    reasons = []
    if qn is not None:
        reasons.append(f"Quality={qn:.2f}*{QUALITY_WEIGHT:.2f}")
    if "abc_local" in scores:
        reasons.append(f"ABC={scores['abc_local']:.2f}*{ABC_LOCAL_WEIGHT:.2f}")
    if "sr_levels" in scores:
        reasons.append(f"SR={scores['sr_levels']:.2f}*{SR_LEVELS_WEIGHT:.2f}")
    if "external_tv" in scores:
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










