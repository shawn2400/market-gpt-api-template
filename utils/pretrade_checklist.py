# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Dict, Any, Optional, List, Iterable
import os

# מודול חיצוני כפי שהשתמשת – נשמר
from utils.indicators_ext import (
    detect_regime,
    compression_bandwidth,
    trend_confidence,
    rsi_composite,
    ema_gap_guard,
)

def _envf(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return default

def _threshold_bw() -> float:
    # תמיכה גם בערך שברי (0.012) וגם אחוזי (1.2)
    raw = _envf("REGIME_COMPRESSION_BW", 1.2)
    return raw * 100.0 if raw < 0.2 else raw

def _as_kl_list(klines: Any) -> List[List[float]]:
    """
    מנרמל klines למבנה List[List[float]] שבו close נמצא באינדקס 4.
    תומך ברשימות של dicts עם מפתח 'close'.
    """
    if klines is None:
        return []
    out: List[List[float]] = []
    try:
        # אם זה כבר רשימת ליסטים/טופלים – נניח close באינדקס 4
        it: Iterable = klines  # type: ignore[assignment]
        for r in it:
            if isinstance(r, (list, tuple)) and len(r) >= 5:
                out.append([float(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4])])
            elif isinstance(r, dict) and "close" in r:
                c = float(r["close"])
                # נמלא ערכים דמה לשדות אחרים במידת הצורך
                out.append([0.0, c, c, c, c])
            else:
                # לא מזוהה – נדלג
                continue
    except Exception:
        return []
    return out

def compute_pretrade_score(klines: List[List[float]] | Any, adx: float, atr_pct: float) -> Dict[str, Any]:
    """
    חתימה תואמת-מפרט: compute_pretrade_score(klines, adx, atr_pct) -> dict עם 'score' ו-'features'.
    atr_pct צפוי באחוזים (למשל 0.8 -> 0.8%)
    תואם גם לקוראים ישנים וגם ללוגיקה המתקדמת שהייתה אצלך.
    """
    kl = _as_kl_list(klines)
    closes = [float(r[4]) for r in kl] if kl else []
    # זיהוי רג'ים/קומפרסיה/טרנד/RSI/פער EMA
    regime = detect_regime(
        float(adx),
        float(atr_pct),
        adx_trend=_envf("REGIME_ADX_TREND", 22.0),
        chop_atr_pct=_envf("REGIME_CHOP_ATR", 0.6),
    )
    comp_bw = compression_bandwidth(closes, period=20)
    tconf   = trend_confidence(closes, float(adx), ema_fast=21, ema_slow=50)
    rsi_c   = rsi_composite(kl, 14, 28)
    ema_ok, ema_gap = ema_gap_guard(closes, period=21, max_gap_pct=_envf("EMA_GAP_MAX_PCT", 6.0))

    # משקולות – נשמר קונפיג דרך ENV
    w_regime = _envf("W_REGIME", 2.0)
    w_comp   = _envf("W_COMPRESSION", 2.0)
    w_trend  = _envf("W_TRENDCONF", 3.0)
    w_rsi    = _envf("W_RSI_COMP", 1.5)
    w_ema    = _envf("W_EMA_GAP", 1.5)

    # ניקוד תכונות
    regime_score = {0: 4.5, 1: 5.5, 2: 7.0}.get(int(regime), 5.0)   # טרנד עדיף
    comp_score   = 7.0 if comp_bw <= _threshold_bw() else 5.0
    trend_score  = max(0.0, min(10.0, float(tconf) * 10.0))
    rsi_score    = 10.0 - abs((float(rsi_c) - 50.0) / 50.0) * 10.0  # ניטרלי-עדין עדיף
    ema_score    = 7.5 if ema_ok else max(2.0, 7.5 - (float(ema_gap) / 2.0))

    total_w = w_regime + w_comp + w_trend + w_rsi + w_ema
    score = (regime_score * w_regime + comp_score * w_comp + trend_score * w_trend +
             rsi_score * w_rsi + ema_score * w_ema) / max(1e-9, total_w)
    score = max(0.0, min(10.0, score))

    return {
        "score": score,
        "features": {
            "regime": regime,
            "compression_bw": comp_bw,
            "trend_conf": tconf,
            "rsi_comp": rsi_c,
            "ema_gap_ok": bool(ema_ok),
            "ema_gap_pct": float(ema_gap),
        },
    }

def entry_window_open(kl: List[List[float]], max_bars: int = 3) -> bool:
    """
    חלון כניסה: אות תקף עד 2–3 נרות.
    (גרסה רזה – תמיד True; ניתן לשלב חותמת זמן בהמשך)
    """
    return True

def estimate_impact_slip_bps(spread_pct: float, atr_pct: float, notional_usdt: float, *, max_bps: float = 25.0) -> float:
    """
    אומדן סליפאג' בסיסי: שילוב spread% + ATR% ביחס לנוטיונל. החזרה ב-bps.
    תואם את הגרסה שסיפקת, עם שמירה על גבול עליון.
    """
    try:
        base = (float(spread_pct) * 50.0) + (float(atr_pct) * 50.0)
        size_factor = 1.0 + min(1.0, float(notional_usdt) / 5000.0) * 0.5  # עד פי 1.5
        bps = base * size_factor
        return float(min(max_bps, max(0.0, bps)))
    except Exception:
        return float(min(max_bps, 10.0))


