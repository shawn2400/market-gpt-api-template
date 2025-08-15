# utils/quality_score.py
import logging
import numpy as np
import pandas as pd
from typing import Any, Optional

def _f(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return float(default)

def _b(x: Any) -> int:
    try:
        if isinstance(x, (bool, np.bool_)):
            return int(bool(x))
        if x is None:
            return 0
        v = float(x)
        return 1 if v != 0.0 else 0
    except Exception:
        return 0

def _infer_direction(last: dict, prev: Optional[dict] = None) -> str:
    try:
        st = last.get("supertrend_dir", None)
        if st is not None:
            return "LONG" if int(st) == 1 else "SHORT"
    except Exception:
        pass
    ema21 = _f(last.get("ema_21"), last.get("close"))
    ema50 = _f(last.get("ema_50"), last.get("close"))
    return "LONG" if ema21 >= ema50 else "SHORT"

def compute_quality_score(
    data: Any,
    direction: Optional[str] = None,
    verbose: bool = False
) -> float:
    try:
        if isinstance(data, pd.DataFrame) and not data.empty:
            last = data.iloc[-1].to_dict()
            prev = data.iloc[-2].to_dict() if len(data) > 1 else None
        elif isinstance(data, dict):
            last = data
            prev = None
        else:
            logging.warning("[quality_score] unsupported data")
            return 0.0

        score = 0.0
        reasons = []

        atr = _f(last.get("atr"), 0)
        if atr > 0:
            score += 1; reasons.append("ATR ok")

        macd = _f(last.get("macd"), 0); macd_signal = _f(last.get("macd_signal"), 0)
        if macd > macd_signal:
            score += 1; reasons.append("MACD > signal")

        rsi = _f(last.get("rsi"), 0)
        if 45 <= rsi <= 65:
            score += 1; reasons.append("RSI neutral")
        if rsi >= 65:
            score += 0.5; reasons.append("RSI high")

        adx = _f(last.get("adx"), 0)
        if adx > 20:
            score += 1; reasons.append("ADX strong")

        vol = _f(last.get("volume"), 0); vol_mean = max(1e-9, _f(last.get("volume_mean"), 1))
        if vol > vol_mean * 1.5:
            score += 1; reasons.append("Volume high")

        close = _f(last.get("close"), 0)
        ema21 = _f(last.get("ema_21"), close)
        ema50 = _f(last.get("ema_50"), close)
        if close > ema21:
            score += 1; reasons.append("> EMA21")
        if close > ema50:
            score += 1; reasons.append("> EMA50")

        if prev is not None:
            try:
                if _f(last.get("ema_21")) > _f(last.get("ema_50")) and _f(prev.get("ema_21")) <= _f(prev.get("ema_50")):
                    score += 1; reasons.append("EMA21 crossed up EMA50")
            except Exception:
                pass

        macd_hist = _f(last.get("macd_hist"), 0)
        if macd_hist > 0:
            score += 1; reasons.append("MACD hist > 0")

        vwap = _f(last.get("vwap"), close)
        if close > vwap:
            score += 1; reasons.append("> VWAP")

        dir_use = (direction or "").strip().upper()
        if dir_use not in ("LONG", "SHORT"):
            dir_use = _infer_direction(last, prev)

        bulls_eng = _b(last.get("is_bullish_engulfing"))
        bears_eng = _b(last.get("is_bearish_engulfing"))
        hammer    = _b(last.get("is_hammer"))
        inv_ham   = _b(last.get("is_inverted_hammer"))
        shoot     = _b(last.get("is_shooting_star"))
        morning   = _b(last.get("is_morning_star"))
        evening   = _b(last.get("is_evening_star"))
        # doji ניטרלי

        if dir_use == "LONG":
            if bulls_eng: score += 1
            if hammer:    score += 1
            if morning:   score += 1
            if bears_eng: score -= 1
            if shoot:     score -= 1
            if evening:   score -= 1
        else:
            if bears_eng: score += 1
            if shoot:     score += 1
            if evening:   score += 1
            if bulls_eng: score -= 1
            if hammer:    score -= 1
            if morning:   score -= 1
            if inv_ham:   score -= 0.5

        final_score = float(min(max(score, 0.0), 10.0))
        if verbose:
            logging.info(f"[quality_score] score={final_score} dir={dir_use} reasons={reasons}")
        return final_score

    except Exception as e:
        logging.error(f"[quality_score] error: {e}", exc_info=True)
        return 0.0

def calculate_quality_score(indicators: dict, direction: Optional[str] = None) -> float:
    return compute_quality_score(indicators, direction=direction, verbose=False)
















