# utils/backtest_utils.py
from __future__ import annotations
from typing import List, Dict, Any, Optional
import pandas as pd

from utils.indicators_utils import prepare_indicators_for_backtest
from utils.sl_tp_utils import calculate_sl_tp
from utils.scanner_utils import fetch_ohlcv

# -------- תבנית נרות --------
def detect_bearish_engulfing(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    prev_green = (df['close'].shift(1) > df['open'].shift(1))
    red_now = (df['close'] < df['open'])
    engulfs = (df['open'] > df['close'].shift(1)) & (df['close'] < df['open'].shift(1))
    df['bearish_engulfing'] = (prev_green & red_now & engulfs).fillna(False)
    return df

def compute_confidence(row: pd.Series) -> float:
    score = 0
    try:
        rsi = float(row.get('rsi', 50) or 50)
        macd_hist = float(row.get('macd_hist', 0) or 0)
        adx = float(row.get('adx', 0) or 0)
        close = float(row.get('close', 0) or 0)
        ema_21 = float(row.get('ema_21', close) or close)
        volume = float(row.get('volume', 0) or 0)
        volume_mean = float(row.get('volume_mean', max(1.0, volume)) or max(1.0, volume))
        obv_trend = bool(row.get('obv_trend', False))
        vwap_trend = bool(row.get('vwap_trend', False))

        if 15 < rsi < 35 or 65 < rsi < 85: score += 1
        if abs(macd_hist) > 0: score += 1
        if adx >= 17: score += 1
        if close > ema_21: score += 1
        if volume > volume_mean * 1.3: score += 1
        if obv_trend: score += 1
        if vwap_trend: score += 1
    except Exception:
        pass
    return round(score / 7, 2)

def _need_cols(df: pd.DataFrame, cols: List[str]) -> None:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"DataFrame missing required columns: {missing}")

def backtest_strategy(
    df: pd.DataFrame,
    rrr_target: float = 2.5,
    min_adx: float = 17.0,
    max_hold: int = 30,
) -> pd.DataFrame:
    if df is None or len(df) < 5:
        raise ValueError("Not enough data to run backtest. Need at least 5 candles.")

    base_cols = ["open", "high", "low", "close", "volume"]
    _need_cols(df, base_cols)

    work = prepare_indicators_for_backtest(df.copy())
    _need_cols(work, ["rsi", "macd_hist", "ema_21", "adx", "stoch_k"])
    atr_available = "atr" in work.columns

    work = detect_bearish_engulfing(work)

    for c in ("signal","entry","stop","tp","rrr","exit","pnl","success","quality_score"):
        work[c] = None

    n = len(work)
    for i in range(1, n):
        row = work.iloc[i]
        entry = None; sl = None; tp = None; signal = None

        rsi = float(row["rsi"]); macd_hist = float(row["macd_hist"]); adx = float(row["adx"])
        close = float(row["close"]); ema21 = float(row["ema_21"]); stoch_k = float(row["stoch_k"])
        atr_val = float(row["atr"]) if atr_available and pd.notna(row["atr"]) else None

        # LONG
        if (rsi < 30 and macd_hist > 0 and close > ema21 and adx >= min_adx and stoch_k < 20):
            entry = close
            sl, tp = calculate_sl_tp(entry_price=entry, direction="LONG", atr=atr_val)
            signal = "LONG"
        # SHORT
        elif (rsi > 70 and macd_hist < 0 and close < ema21 and adx >= min_adx
              and bool(row.get("bearish_engulfing", False)) and stoch_k > 80):
            entry = close
            sl, tp = calculate_sl_tp(entry_price=entry, direction="SHORT", atr=atr_val)
            signal = "SHORT"

        if signal and entry and sl is not None and tp is not None:
            work.loc[i, "signal"] = signal
            work.loc[i, "entry"] = float(entry)
            work.loc[i, "stop"] = float(sl)
            work.loc[i, "tp"] = float(tp)
            work.loc[i, "rrr"] = float(rrr_target)
            work.loc[i, "quality_score"] = compute_confidence(row)

            for j in range(i + 1, min(i + max_hold, n)):
                close_j = float(work["close"].iloc[j])
                if signal == "LONG":
                    if close_j <= sl:
                        work.loc[i, "exit"] = close_j
                        work.loc[i, "pnl"] = close_j - entry
                        work.loc[i, "success"] = False
                        break
                    if close_j >= tp:
                        work.loc[i, "exit"] = close_j
                        work.loc[i, "pnl"] = close_j - entry
                        work.loc[i, "success"] = True
                        break
                else:
                    if close_j >= sl:
                        work.loc[i, "exit"] = close_j
                        work.loc[i, "pnl"] = entry - close_j
                        work.loc[i, "success"] = False
                        break
                    if close_j <= tp:
                        work.loc[i, "exit"] = close_j
                        work.loc[i, "pnl"] = entry - close_j
                        work.loc[i, "success"] = True
                        break

            if pd.isna(work.loc[i, "exit"]):
                last_close = float(work["close"].iloc[min(i + max_hold - 1, n - 1)])
                work.loc[i, "exit"] = last_close
                work.loc[i, "pnl"] = (last_close - entry) if signal == "LONG" else (entry - last_close)
                work.loc[i, "success"] = bool(work.loc[i, "pnl"] > 0)

    ts_col = "timestamp" if "timestamp" in work.columns else ("open_time" if "open_time" in work.columns else None)
    cols_out = ["signal","entry","stop","tp","exit","rrr","pnl","success","quality_score"]
    out_cols = ([ts_col] + cols_out) if ts_col else cols_out
    result = work[work["signal"].notnull()][out_cols].reset_index(drop=True)
    return result

async def run_backtest_for_symbol(symbol: str, timeframe: str = "15m", limit: int = 200, slippage_pct: float = 0.1) -> Dict[str, Any]:
    df = await fetch_ohlcv(symbol, interval=timeframe, limit=limit)
    if df is None or df.empty:
        return {"symbol": symbol.upper(), "timeframe": timeframe, "trades": []}
    # הפוך ל-regular cols (לא index-based)
    out = df.reset_index()
    out.rename(columns={"open_time": "timestamp"}, inplace=True)
    trades = backtest_strategy(out)
    return {"symbol": symbol.upper(), "timeframe": timeframe, "count": int(len(trades)), "trades": trades.to_dict(orient="records")}















