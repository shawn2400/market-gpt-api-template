# -*- coding: utf-8 -*-
from __future__ import annotations
import os, time, json
from typing import Dict, Any, Optional
from contextlib import suppress

try:
    from utils.learning_loops import bandit_update, resolve_session_bucket, resolve_regime  # type: ignore
except Exception:
    async def bandit_update(context, arm, reward):  # type: ignore
        return None
    def resolve_session_bucket(utc_hour: int) -> str:  # type: ignore
        return "OTHER"
    def resolve_regime(adx: float, atr_pct: float, adx_trend: float = 22.0, chop_atr_pct: float = 0.6) -> str:  # type: ignore
        return "CH"

# אופציונלי: לצורך חישוב regime דחוף (כשאין לנו קונטקסט מלא)
try:
    from utils.indicators_ext import compression_bandwidth  # type: ignore
except Exception:
    def compression_bandwidth(closes, period=20):  # type: ignore
        return 999.0

def _safe_float(x) -> float:
    try:
        return float(x)
    except Exception:
        return 0.0

def _r_multiple(entry: float, exit: float, side: str, atr: float) -> float:
    """
    R = (PnL per unit) / ATR  (נורמליזציה גסה)
    """
    side = (side or "").upper()
    if entry <= 0 or atr <= 0 or exit <= 0:
        return 0.0
    pnl = (exit - entry) if side == "BUY" else (entry - exit)
    return max(-2.0, min(3.0, pnl / atr))

async def on_trade_close_reward(symbol: str,
                                side: str,
                                entry: float,
                                exit: float,
                                used_profile: str,
                                indicators: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """
    מחושב R-multiple פשוט ומעדכן Bandit (ε-greedy) לפי ההקשר regime×session.
    indicators יכול להכיל {"adx","atr","price"}; אם חסר — נשתמש בערכי דיפולט.
    """
    ind = indicators or {}
    atr = _safe_float(ind.get("atr", 0.0))
    adx = _safe_float(ind.get("adx", 0.0))
    price = _safe_float(ind.get("price", 0.0))
    atr_pct = (atr / price) * 100.0 if price > 0 else 0.0

    r = _r_multiple(entry, exit, side, atr)
    session = resolve_session_bucket(time.gmtime().tm_hour)
    regime = resolve_regime(adx, atr_pct, adx_trend=float(os.getenv("REGIME_ADX_TREND","22")), chop_atr_pct=float(os.getenv("REGIME_CHOP_ATR","0.6")))
    ctx = {"regime": regime, "session": session, "symbol": (symbol or "").upper()}

    with suppress(Exception):
        await bandit_update(ctx, (used_profile or "BASE").upper(), r)

    return {"ok": True, "context": ctx, "reward": r}
