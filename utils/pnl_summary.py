# utils/pnl_summary.py
from __future__ import annotations
import pandas as pd
from typing import List, Dict, Any

def summarize_trades(trades: List[Dict[str, Any]]) -> pd.DataFrame:
    if not trades:
        return pd.DataFrame(columns=["symbol", "side", "entry_price", "exit_price", "pnl", "timestamp"])

    df = pd.DataFrame(trades)
    df["pnl"] = df.get("realized_pnl", 0.0)
    df["timestamp"] = pd.to_datetime(df.get("updated_at", pd.Timestamp.now()))
    return df[["symbol", "side", "entry_price", "exit_price", "pnl", "timestamp"]]


