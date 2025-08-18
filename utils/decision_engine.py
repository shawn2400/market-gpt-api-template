# utils/decision_engine.py
from __future__ import annotations
from typing import List, Dict, Any, Optional, Tuple
import math

# משקלים מה-ENV (עם דיפולטים), מנורמלים לסכום 1
try:
    from utils.scoring import weights_norm  # W_QS, W_SP, W_ETA, W_VOL, W_CORR → נרמול
except Exception as exc:  # fallback בטוח
    def weights_norm() -> Tuple[float, float, float, float, float]:
        # איכות/הצלחה/מהירות/תנודתיות/דקורלציה
        base = (0.40, 0.25, 0.15, 0.10, 0.10)
        s = sum(base)
        return tuple(x / s for x in base)  # type: ignore

# ------- עזרי נרמול -------

def _to_float(x, default: float = float("nan")) -> float:
    try:
        v = float(x)
        return v if math.isfinite(v) else default
    except Exception:
        return default

def _norm_series(vals: List[float], *, higher_is_better: bool = True) -> List[float]:
    clean = [v for v in vals if math.isfinite(v)]
    if not clean:
        return [0.5] * len(vals)  # ללא מידע – אמצע
    lo, hi = min(clean), max(clean)
    if not math.isfinite(lo) or not math.isfinite(hi) or abs(hi - lo) < 1e-12:
        return [0.5] * len(vals)
    out = []
    for v in vals:
        if not math.isfinite(v):
            out.append(0.5)
            continue
        z = (v - lo) / (hi - lo)  # 0..1
        out.append(z if higher_is_better else (1.0 - z))
    return out

# ------- חילוץ פיצ'רים גמיש (מקבל שמות שונים) -------

def _pick(d: Dict[str, Any], keys: List[str]) -> Optional[float]:
    for k in keys:
        if k in d:
            return _to_float(d.get(k))
    return None

def _extract_features(c: Dict[str, Any]) -> Dict[str, float]:
    """
    מחלץ:
      - qs: quality score (0..10/100) → ננרמל פנימית
      - sp: success/win rate (0..100)
      - eta: זמן/מהירות (קטן=טוב)
      - vol: תנודתיות (גדול=טוב)
      - decorr: דקורלציה מול BTC (גדול=טוב). אם יש corr_btc → משתמשים ב-1-|corr|
    """
    qs = _pick(c, ["quality", "quality_score", "qs", "score"])
    if math.isfinite(qs if qs is not None else float("nan")) and qs and qs > 10:
        qs = qs / 10.0  # אם הגיע בסקאלה 0..100

    sp = _pick(c, ["success", "win_rate", "success_rate"])
    eta = _pick(c, ["eta", "eta_minutes", "eta_min", "time_to_signal", "time_minutes"])
    vol = _pick(c, ["volatility", "vol", "atr_pct", "atrp", "stdev_pct"])
    decorr = _pick(c, ["decorrelation", "decorr", "decorrelation_vs_btc", "decorr_btc"])

    # אם יש קורלציה (corr_btc), הפוך לדקורלציה
    corr = _pick(c, ["corr_btc", "correlation_btc"])
    if corr is not None and (decorrelation := 1.0 - abs(float(corr))) is not None:
        decorr = decorrelation if math.isfinite(decorrelation) else decorr

    return {
        "qs": _to_float(qs),
        "sp": _to_float(sp),
        "eta": _to_float(eta),
        "vol": _to_float(vol),
        "decorr": _to_float(decorr),
    }

# ------- API ציבורי -------

def select_best_trades(
    candidates: List[Dict[str, Any]],
    top_n: int = 5,
    diversify_by_symbol: bool = True,
) -> List[Dict[str, Any]]:
    """
    מקבל רשימת מועמדים (dict לכל סימבול/סיגנל) ומחזיר את הטופ N לפי ציון משוקלל.
    תומך במפתחות שונים (ראה _extract_features).
    אם diversify=True – מונע בחירה מרובה של אותו symbol.
    """
    if not candidates:
        return []

    feats = [_extract_features(c) for c in candidates]

    qs_norm   = _norm_series([f["qs"]   for f in feats], higher_is_better=True)
    sp_norm   = _norm_series([f["sp"]   for f in feats], higher_is_better=True)
    eta_norm  = _norm_series([f["eta"]  for f in feats], higher_is_better=False)  # קטן=טוב
    vol_norm  = _norm_series([f["vol"]  for f in feats], higher_is_better=True)
    dc_norm   = _norm_series([f["decorr"] for f in feats], higher_is_better=True)

    w_qs, w_sp, w_eta, w_vol, w_dc = weights_norm()

    scored: List[Tuple[float, int]] = []
    for i in range(len(candidates)):
        score = (w_qs * qs_norm[i] +
                 w_sp * sp_norm[i] +
                 w_eta * eta_norm[i] +
                 w_vol * vol_norm[i] +
                 w_dc * dc_norm[i])
        scored.append((float(score), i))

    # מיון יורד
    scored.sort(key=lambda t: t[0], reverse=True)

    picked: List[Dict[str, Any]] = []
    seen: set[str] = set()

    for s, idx in scored:
        c = dict(candidates[idx])  # העתק
        c["_decision"] = {
            "score_weighted_0_1": round(s, 6),
            "components": {
                "qs": qs_norm[idx], "sp": sp_norm[idx], "speed": eta_norm[idx],
                "vol": vol_norm[idx], "decorr": dc_norm[idx],
                "weights": {"qs": w_qs, "sp": w_sp, "eta": w_eta, "vol": w_vol, "decorr": w_dc},
            }
        }

        if diversify_by_symbol:
            sym = str(c.get("symbol") or c.get("base") or c.get("ticker") or "")
            if sym and sym in seen:
                continue
            if sym:
                seen.add(sym)

        picked.append(c)
        if len(picked) >= int(top_n):
            break

    return picked




