# utils/risk_checker.py
from __future__ import annotations
import os, logging, math
from typing import Dict, Any, Optional

from utils.binance_client import (
    get_klines_df, futures_mark_price, get_price
)

logger = logging.getLogger("algogpt.risk_checker")

# ===== ENV =====
RISK_CHECK_ENABLE = os.getenv("RISK_CHECK_ENABLE", "1").lower() in ("1","true","yes","on")
MAX_ATR_PCT       = float(os.getenv("MAX_ATR_PCT", "2.5"))                   # אחוז מהמחיר
SPREAD_MAX_BPS    = float(os.getenv("SOP_MARK_INDEX_MAX_GAP_BPS", "20.0"))   # bps
PUMP_NUKE_5M_PCT  = float(os.getenv("SOP_PUMP_NUKE_MAX_5M_PCT", "1.0"))      # %
MIN_VOLUME        = float(os.getenv("MIN_VOLUME", "0"))
FEAT_BTC_GATE     = os.getenv("FEAT_BTC_GATE", "0").lower() in ("1","true","on")

def _safe_pct(a: float, b: float) -> float:
    if b <= 0: return 0.0
    return (a / b) * 100.0

def _ema(vals, period=14):
    k = 2 / (period + 1)
    ema = None
    out = []
    for v in vals:
        ema = v if ema is None else (v * k + ema * (1 - k))
        out.append(ema)
    return out

def _atr_pct_from_df(df) -> float:
    if df is None or getattr(df, "empty", True):
        return 0.0
    high = df["high"].astype(float).tolist()
    low  = df["low"].astype(float).tolist()
    close= df["close"].astype(float).tolist()
    if len(close) < 15:
        return 0.0
    trs = []
    prev_close = None
    for h,l,c in zip(high, low, close):
        if prev_close is None:
            tr = h - l
        else:
            tr = max(h - l, abs(h - prev_close), abs(l - prev_close))
        trs.append(tr)
        prev_close = c
    atr = _ema(trs, 14)[-1]
    last = close[-1]
    return _safe_pct(atr, last)

def _mark_last_spread_bps(symbol: str) -> float:
    try:
        mark = float(futures_mark_price(symbol) or 0.0)
        last = float(get_price(symbol) or 0.0)
        if mark <= 0 or last <= 0:
            return 0.0
        bps = abs(last - mark) / mark * 10000.0
        return float(bps)
    except Exception:
        return 0.0

def _btc_pump_nuke_pct() -> float:
    try:
        df_btc = get_klines_df("BTCUSDT", interval="5m", limit=6)
        if df_btc is None or getattr(df_btc, "empty", True):
            return 0.0
        c0 = float(df_btc["close"].iloc[-6])
        c1 = float(df_btc["close"].iloc[-1])
        return abs((c1 - c0) / c0) * 100.0
    except Exception:
        return 0.0

def _volume_ok(df) -> bool:
    if MIN_VOLUME <= 0:  # כבוי
        return True
    try:
        v = float(df["volume"].iloc[-1])
        return v >= MIN_VOLUME
    except Exception:
        return True  # אל תחסום על חוסר נתונים

def pre_trade_risk_check(symbol: str, side: str, leverage: int, entry: Optional[float] = None) -> Dict[str, Any]:
    """
    בדיקת סיכונים לפני טרייד. לא זורק חריגות — תמיד מחזיר dict.
    """
    if not RISK_CHECK_ENABLE:
        return {"ok": True, "score": 100.0, "reasons": ["risk_disabled"], "metrics": {}}

    sym = symbol.upper().strip()
    side_u = side.upper().strip()
    reasons = []
    score = 100.0
    metrics: Dict[str, Any] = {}

    # ATR%
    try:
        df = get_klines_df(sym, interval="5m", limit=60)
        atr_pct = _atr_pct_from_df(df)
        metrics["atr_pct_5m"] = atr_pct
        if atr_pct > MAX_ATR_PCT:
            reasons.append(f"atr_pct_gt_{MAX_ATR_PCT}")
            score -= min(40.0, (atr_pct - MAX_ATR_PCT) * 5.0)
        if not _volume_ok(df):
            reasons.append("low_volume")
            score -= 10.0
    except Exception as e:
        metrics["atr_err"] = str(e)
        reasons.append("atr_unavailable")
        score -= 5.0

    # Spread Mark-Last
    spread_bps = _mark_last_spread_bps(sym)
    metrics["spread_bps"] = spread_bps
    if spread_bps > SPREAD_MAX_BPS:
        reasons.append("wide_spread")
        score -= min(25.0, (spread_bps - SPREAD_MAX_BPS) * 0.8)

    # BTC Gate
    if FEAT_BTC_GATE:
        btc_5m = _btc_pump_nuke_pct()
        metrics["btc_5m_abs_pct"] = btc_5m
        if btc_5m > PUMP_NUKE_5M_PCT:
            reasons.append("btc_pump_nuke")
            score -= 20.0

    score = max(0.0, min(100.0, score))
    ok = score >= 60.0 and ("wide_spread" not in reasons)

    return {"ok": ok, "score": score, "reasons": reasons, "metrics": metrics, "symbol": sym, "side": side_u, "lev": leverage}
