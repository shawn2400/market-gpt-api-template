# utils/decision_engine.py
from __future__ import annotations
from typing import List, Dict, Any, Tuple
import math

try:
    # (W_QS,W_SP,W_ETA,W_VOL,W_CORR) מנורמלים מה־env (עם דיפולטים סבירים)
    from utils.scoring import weights_norm
except Exception:
    # ברירת מחדל קשיחה אם אין קובץ/ייבוא (לא אמור לקרות אצלך)
    def weights_norm() -> Tuple[float, float, float, float, float]:
        return (0.40, 0.25, 0.15, 0.10, 0.10)

def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))

def _safe_float(x, default: float = 0.0) -> float:
    try:
        v = float(x)
        if math.isfinite(v):
            return v
        return default
    except Exception:
        return default

def _normalize_quality(score_0_10: float) -> float:
    return _clamp(_safe_float(score_0_10, 0.0) / 10.0, 0.0, 1.0)

def _normalize_success(success_pct_0_100: float) -> float:
    return _clamp(_safe_float(success_pct_0_100, 0.0) / 100.0, 0.0, 1.0)

def _normalize_inv_by_max(values: List[float], v: float) -> float:
    """הופך סולם: קטן=טוב. אם כולם 0 → 1.0 כדי לא לפגוע בנרמול."""
    vmax = max([_safe_float(x, 0.0) for x in values] + [0.0])
    if vmax <= 0:
        return 1.0
    return _clamp(1.0 - (_safe_float(v, 0.0) / vmax), 0.0, 1.0)

def _normalize_decorr(cand: Dict[str, Any]) -> float:
    """
    תומך בשדות שונים:
    - 'decorr' (0..1 – גדול=טוב), או
    - 'corr_btc'/'corr' (-1..1 או 0..1) → נשתמש ב- 1 - |corr|.
    חסר/לא תקף → 0.5.
    """
    if "decorr" in cand:
        return _clamp(_safe_float(cand.get("decorr"), 0.5), 0.0, 1.0)
    corr = cand.get("corr_btc", cand.get("corr"))
    if corr is None:
        return 0.5
    c = _safe_float(corr, 0.0)
    # אם נראה כמו טווח -1..1:
    if -1.0 <= c <= 1.0:
        return _clamp(1.0 - abs(c), 0.0, 1.0)
    # אחרת נניח 0..1:
    return _clamp(1.0 - _clamp(c, 0.0, 1.0), 0.0, 1.0)

def _composite_score(cands: List[Dict[str, Any]], c: Dict[str, Any]) -> Tuple[float, Dict[str, float]]:
    W_QS, W_SP, W_ETA, W_VOL, W_CORR = weights_norm()

    # איכות/הצלחה
    qs = _normalize_quality(c.get("score", c.get("quality", 0.0)))
    sp = _normalize_success(c.get("success", c.get("win_rate", 0.0)))

    # מהירות (ETA נמוך=טוב) + תנודתיות (נמוך=טוב)
    etas = [x.get("eta", x.get("speed", 0.0)) for x in cands]
    vols = [x.get("volatility", x.get("vol", 0.0)) for x in cands]
    eta_raw = c.get("eta", c.get("speed", 0.0))
    vol_raw = c.get("volatility", c.get("vol", 0.0))
    eta = _normalize_inv_by_max(etas, eta_raw)
    vol = _normalize_inv_by_max(vols, vol_raw)

    # דקורלציה
    de  = _normalize_decorr(c)

    parts = {
        "qs": qs, "sp": sp, "eta": eta, "vol": vol, "decorr": de,
        "W_QS": W_QS, "W_SP": W_SP, "W_ETA": W_ETA, "W_VOL": W_VOL, "W_CORR": W_CORR
    }
    total = (qs * W_QS) + (sp * W_SP) + (eta * W_ETA) + (vol * W_VOL) + (de * W_CORR)
    return float(total), parts

def select_best_trades(
    candidates: List[Dict[str, Any]],
    top_n: int = 5,
    diversify_by_symbol: bool = True,
) -> List[Dict[str, Any]]:
    """
    מחזיר רשימת מועמדים מסודרת לפי ניקוד מרוכב.
    אם diversify_by_symbol=True – נמנע מכפילויות סימבול (אם היו).
    """
    if not candidates:
        return []

    # חישוב ניקוד
    scored: List[Dict[str, Any]] = []
    for c in candidates:
        total, parts = _composite_score(candidates, c)
        item = dict(c)
        item["_score_composite"] = total
        item["_score_parts"] = parts
        scored.append(item)

    # סידור עם "טיי־ברייקרים" רכים:
    # 1) ניקוד מרוכב יורד
    # 2) איכות 0..10 יורד
    # 3) ETA עולה
    scored.sort(
        key=lambda x: (
            -_safe_float(x.get("_score_composite"), 0.0),
            -_safe_float(x.get("score", x.get("quality", 0.0)), 0.0),
             _safe_float(x.get("eta", x.get("speed", 0.0)), 1e9),
        )
    )

    # Diversify לפי סימבול
    out: List[Dict[str, Any]] = []
    seen = set()
    for it in scored:
        sym = str(it.get("symbol", "")).upper()
        if diversify_by_symbol and sym in seen:
            continue
        seen.add(sym)
        out.append({
            "rank": len(out) + 1,
            "symbol": sym,
            "side": it.get("side"),
            "score": round(_safe_float(it.get("_score_composite"), 0.0), 6),
            "components": {
                "quality": _safe_float(it.get("score", it.get("quality", 0.0)), 0.0),
                "success_pct": _safe_float(it.get("success", it.get("win_rate", 0.0)), 0.0),
                "eta": _safe_float(it.get("eta", it.get("speed", 0.0)), 0.0),
                "volatility": _safe_float(it.get("volatility", it.get("vol", 0.0)), 0.0),
                "decorr": _normalize_decorr(it),
                "weights": it.get("_score_parts", {}),
            },
            "raw": it,  # שומר את המקור (נוח לדיבוג)
        })
        if len(out) >= int(top_n):
            break

    return out






