# utils/strategy_auto.py
from __future__ import annotations
import os, json, math
from typing import Dict, Any, Optional, Tuple

import pandas as pd

from utils.binance_client import get_klines_df, futures_mark_price
from utils.indicators import adx as _adx
# EMA - נחשב ישירות מפנדהס

def _ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False).mean()

def _lev_from_adx(adx_val: float) -> int:
    """
    מיפוי מינימום-לברג' לפי LEV_ADX_MAP_JSON, נופל ל-10 אם אין התאמה.
    """
    raw = os.getenv("LEV_ADX_MAP_JSON", '{"30":15,"25":12,"20":9,"0":7}')
    try:
        m = {int(k): int(v) for k, v in json.loads(raw).items()}
    except Exception:
        m = {30: 15, 25: 12, 20: 9, 0: 7}
    best = 7
    for k in sorted(m.keys(), reverse=True):
        if adx_val >= k:
            best = m[k]
            break
    cap_json = os.getenv("LEVERAGE_SYMBOL_CAPS", '{"BTCUSDT":15}')
    try:
        caps = json.loads(cap_json)
    except Exception:
        caps = {"BTCUSDT": 15}
    return min(best, int(caps.get("BTCUSDT", 15)))

def decide(symbol: str, budget_usd: float, qty_override: Optional[float] = None) -> Dict[str, Any]:
    """
    מחזיר החלטה אוטומטית: side (BUY/SELL), position_side (LONG/SHORT), leverage, quantity.
    בסיס: EMA21/EMA50 + ADX (15m). אם חד משמעי → LONG/SHORT, אחרת נייטרלי.
    """
    sym = symbol.upper()
    df = get_klines_df(sym, interval=os.getenv("DEFAULT_INTERVAL", "15m"), limit=120)
    if df is None or getattr(df, "empty", False):
        raise ValueError("no_klines")

    close = df["close"].astype(float)
    ema21 = _ema(close, 21)
    ema50 = _ema(close, 50)
    adx_ser = _adx(df)
    adx_now = float(adx_ser.iloc[-1])

    trend_up = ema21.iloc[-1] > ema50.iloc[-1]
    trend_down = ema21.iloc[-1] < ema50.iloc[-1]
    strong = adx_now >= 18.0

    if trend_up and strong:
        side = "BUY"; position_side = "LONG"
    elif trend_down and strong:
        side = "SELL"; position_side = "SHORT"
    else:
        # ניטרלי – נלך עם כיוון קל של EMA גם אם ADX חלש, אבל נוריד מינוף
        side = "BUY" if ema21.iloc[-1] >= ema50.iloc[-1] else "SELL"
        position_side = "LONG" if side == "BUY" else "SHORT"
        adx_now = max(adx_now, 0.0)

    lev = _lev_from_adx(adx_now)

    # חישוב כמות: אם נשלח qty_override – נכבד; אחרת לפי תקציב/מחיר
    qty = qty_override
    if not qty or qty <= 0:
        price = float(futures_mark_price(sym) or 0.0)
        if price <= 0:
            raise ValueError("no_price")
        # מינוף משפיע על בטחונות, אבל הכמות לפי notional רצוי ≈ budget_usd
        # נסה להיכנס בכ- budget_usd / price
        qty = max(0.0, budget_usd / price)
        # עיגול ייעשה ב-executor לפי ה-step של הסימבול

    return {
        "symbol": sym,
        "side": side,
        "position_side": position_side,
        "leverage": lev,
        "quantity": qty,
        "adx": adx_now,
        "ema21": float(ema21.iloc[-1]),
        "ema50": float(ema50.iloc[-1]),
        "confidence": (2 if strong else 1),  # 2=גבוה, 1=בינוני
    }
