# utils/anchor.py
import requests
import pandas as pd
import numpy as np
from dataclasses import dataclass
from typing import Literal
import time

from utils import config as cfg
from utils.indicators import prepare_indicators_for_backtest

FUTURES_BASE = cfg.BINANCE_FUTURES_HTTP_BASE

@dataclass
class AnchorDecision:
    mode_requested: Literal["LONG","SHORT"]
    mode_applied: Literal["LONG","SHORT"]
    bias: str
    score: float
    allow: bool
    severity: str
    reason: str


def _fetch_klines(symbol: str, interval: str, limit: int = 200) -> pd.DataFrame:
    url = f"{FUTURES_BASE}/fapi/v1/klines"
    r = requests.get(url, params={"symbol": symbol, "interval": interval, "limit": limit}, timeout=10)
    r.raise_for_status()
    arr = r.json()

    cols = ["open_time","open","high","low","close","volume","close_time",
            "qv","nTrades","taker_base","taker_quote","x"]
    df = pd.DataFrame(arr, columns=cols[:len(arr[0])])
    for c in ("open","high","low","close","volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def _calc_bias(df: pd.DataFrame) -> tuple[str, float]:
    ind = prepare_indicators_for_backtest(df)
    if ind.empty:
        return "NEUTRAL", 50.0

    row = ind.iloc[-1]
    score = 50.0
    bias = "NEUTRAL"

    # EMA Bias
    if row["ema21"] > row["ema50"]:
        score += 15
        bias = "UP"
    elif row["ema21"] < row["ema50"]:
        score -= 15
        bias = "DOWN"

    # RSI Bias
    if row["rsi"] > 60:
        score += 15
        bias = "UP"
    elif row["rsi"] < 40:
        score -= 15
        bias = "DOWN"

    # OBV Bias
    if "obv" in row and row["obv"] > 0:
        score += 10
    elif "obv" in row and row["obv"] < 0:
        score -= 10

    return bias, max(0.0, min(100.0, score))


def evaluate_anchor(side: str) -> AnchorDecision:
    """
    Anchor אמיתי על BTCUSDT בשלושה טיימפריימים: 15m, 1h, 4h.
    אם שניים מתוך שלושה מחזקים את הצד -> מאפשרים.
    """
    side = side.upper()
    if side not in ("LONG", "SHORT"):
        raise ValueError(f"Invalid side={side}")

    frames = ["15m", "1h", "4h"]
    results = []
    for f in frames:
        try:
            df = _fetch_klines("BTCUSDT", f)
            bias, score = _calc_bias(df)
            results.append((bias, score))
        except Exception as e:
            results.append(("NEUTRAL", 50.0))

    ups = sum(1 for b, _ in results if b == "UP")
    downs = sum(1 for b, _ in results if b == "DOWN")

    if side == "LONG":
        allow = ups >= 2
        severity = "high" if downs >= 2 else "low"
        bias = "UP" if ups >= 2 else "NEUTRAL"
        score = np.mean([s for _, s in results])
    else:
        allow = downs >= 2
        severity = "high" if ups >= 2 else "low"
        bias = "DOWN" if downs >= 2 else "NEUTRAL"
        score = np.mean([s for _, s in results])

    return AnchorDecision(
        mode_requested=side,
        mode_applied=side if allow else ("SHORT" if side == "LONG" else "LONG"),
        bias=bias,
        score=round(score, 2),
        allow=allow,
        severity=severity,
        reason=f"frames={results}"
    )





































