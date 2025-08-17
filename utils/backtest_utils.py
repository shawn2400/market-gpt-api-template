# utils/backtest_utils.py

import pandas as pd
from utils.get_klines import get_klines
from utils.indicators import compute_indicators
from utils.quality_score import compute_quality_score
from utils.scanner_utils import _extract_last_fields

def run_backtest(symbol: str, interval: str = "15m", limit: int = 200):
    df = get_klines(symbol=symbol, interval=interval, futures=True, limit=limit)
    if df is None or df.empty:
        return None

    df = compute_indicators(df)
    df["score"] = compute_quality_score(df)

    results = []
    for i in range(50, len(df)):
        row = df.iloc[i]
        extracted = _extract_last_fields(df.iloc[i : i + 1])
        results.append({
            "timestamp": row["timestamp"],
            "price": row["close"],
            "score": row["score"],
            **extracted,
        })

    return results[-50:]















