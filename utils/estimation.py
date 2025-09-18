# utils/estimation.py
from __future__ import annotations
import math
from typing import Dict

def _tf_minutes(tf: str) -> int:
    tf = (tf or "").strip().lower()
    if tf.endswith("m"): return int(tf[:-1])
    if tf.endswith("h"): return int(tf[:-1]) * 60
    if tf.endswith("d"): return int(tf[:-1]) * 60 * 24
    return 15

def suggest_entry(sig: Dict) -> Dict:
    """בחר MARKET אם ADX>=25, אחרת LIMIT על EMA21."""
    d = sig.get("details") or {}
    adx  = float(d.get("adx") or 0)
    ema21 = float(d.get("ema21") or 0)
    if adx >= 25:
        return {"type": "MARKET", "limit_price": None}
    return {"type": "LIMIT", "limit_price": ema21 or None}

def compute_sl_tp(sig: Dict) -> Dict:
    """
    SL/TP לפי R = max(ATR, 0.1%*close) עם fallbacks:
    TP1=0.5R, TP2=1R, TP3=2R בכיוון הטרייד; SL=1R בצד ההפוך.
    """
    d = sig.get("details") or {}
    side  = (sig.get("side") or "").upper()
    close = float(d.get("close") or 0)
    atr   = float(d.get("atr") or (0.004 * close))
    R = max(atr, 0.001 * close)

    if side == "BUY":
        sl  = close - 1.0 * R
        tp1 = close + 0.5 * R
        tp2 = close + 1.0 * R
        tp3 = close + 2.0 * R
    else:
        sl  = close + 1.0 * R
        tp1 = close - 0.5 * R
        tp2 = close - 1.0 * R
        tp3 = close - 2.0 * R

    return {"sl": sl, "tp1": tp1, "tp2": tp2, "tp3": tp3, "R": R}

def probabilities(sig: Dict) -> Dict:
    """הסתברויות גסות יחסית לציון (+בונוס קטן אם ADX>=25)."""
    score = float(sig.get("score") or 0.0)
    d = sig.get("details") or {}
    adx = float(d.get("adx") or 0)

    base = max(0.0, score - 7.0)
    p1 = 0.55 + base * 0.04
    p2 = 0.40 + base * 0.03
    p3 = 0.25 + base * 0.02
    if adx >= 25:
        p1 += 0.03; p2 += 0.02; p3 += 0.01

    clamp = lambda x, lo, hi: min(max(x, lo), hi)
    return {
        "p_tp1": clamp(p1, 0.05, 0.95),
        "p_tp2": clamp(p2, 0.03, 0.85),
        "p_tp3": clamp(p3, 0.02, 0.75),
    }

def eta_minutes(sig: Dict, R: float) -> Dict:
    """
    זמן משוער ל-TPs: מהירות ~ (|close-ema21| + ATR)/tf_minutes → דקות ל-R.
    """
    d = sig.get("details") or {}
    close = float(d.get("close") or 0)
    ema21 = float(d.get("ema21") or close)
    atr   = float(d.get("atr") or (0.004 * close))
    tfm   = _tf_minutes(sig.get("timeframe") or "15m")
    speed_per_min = max((abs(close - ema21) + atr) / max(tfm, 1), 1e-9)
    minutes_per_R = max(R / speed_per_min, 1.0)

    return {
        "eta_tp1_min": int(0.5 * minutes_per_R),
        "eta_tp2_min": int(1.0 * minutes_per_R),
        "eta_tp3_min": int(2.0 * minutes_per_R),
    }

def profit_usd(sig: Dict, tp_levels: Dict, leverage: float, stake_usdt: float) -> Dict:
    """
    רווח $ משוער לכל TP: position ≈ (stake*lev)/close; PnL = pos*(Δמחיר) בכיוון הטרייד.
    """
    d = sig.get("details") or {}
    side  = (sig.get("side") or "").upper()
    close = float(d.get("close") or 0)
    size  = (stake_usdt * leverage) / max(close, 1e-9)

    def pnl_at(target: float) -> float:
        if side == "BUY":
            return size * (target - close)
        return size * (close - target)

    return {
        "pnl_tp1": pnl_at(tp_levels["tp1"]),
        "pnl_tp2": pnl_at(tp_levels["tp2"]),
        "pnl_tp3": pnl_at(tp_levels["tp3"]),
    }

def brief_reason(sig: Dict) -> str:
    """שורה מסבירה קצרה למה האיתות נבחר."""
    d = sig.get("details") or {}
    trend = d.get("trend") or "-"
    rsi   = d.get("rsi")
    adx   = d.get("adx")
    note  = sig.get("note") or ""
    return f"Trend {trend}, RSI {int(rsi or 0)}, ADX {int(adx or 0)} — {note}"
