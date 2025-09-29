# core/signal_fuser.py
from __future__ import annotations
from typing import Dict, Any, List
from utils.indicators_registry import run_all
from utils.config import get_settings as cfg
from utils.quality import compute_quality
from utils.book_gates import gate_mark_index_sanity, gate_spread_depth
from utils.funding_bias import funding_bias as funding_async  # async (14)

def fuse_signals(df, *, symbol: str, tf: str, feeds: dict) -> Dict[str, Any]:
    """
    feeds צפוי לכלול לפי זמינותך:
      delta_per_bar, oi_df, df_spot, df_mark, best_bid, best_ask, bid_qty, ask_qty
    """
    # הרצת כל האינדיקים (ללא funding – async)
    res = run_all(df, symbol=symbol, tf=tf, **feeds)

    # דוגמאות Gates לפני טרייד:
    sanity = gate_mark_index_sanity(mark=feeds.get("mark"), index=feeds.get("index"), max_gap_bps=20.0)
    if not sanity["ok"]: return {"ok": False, "reason": sanity["code"], "indicators": res}

    spread = gate_spread_depth(best_bid=feeds.get("best_bid"), best_ask=feeds.get("best_ask"),
                               bid_qty=feeds.get("bid_qty"), ask_qty=feeds.get("ask_qty"),
                               max_spread_bps=3.0, min_top_qty=0.0)
    if not spread["ok"]: return {"ok": False, "reason": spread["code"], "indicators": res}

    # איסוף אותות מובילים
    signals: List[Dict[str,Any]] = []
    for key in ("mc_b","qqe","alpha","smc","invictus","squeeze","donchian","cvd","oi","basis"):
        r = res.get(key) or {}
        for s in (r.get("signals") or []):
            signals.append({"name":key, **s})
    signals.sort(key=lambda x: x.get("strength",0), reverse=True)
    lead = signals[0] if signals else None
    if not lead:
        return {"ok": False, "reason":"no_signal", "indicators": res}

    side = lead["side"]
    px = float(df["close"].iloc[-1])

    # TP/SL ע"פ Alpha/ATR
    alpha = res.get("alpha", {})
    atr_val = float(alpha.get("series",{}).get("atr", pd.Series([0])).iloc[-1]) if alpha.get("series") else 0.0
    sl_mult = 1.5; tp1_mult = 1.8; tp2_mult = 3.2
    sl  = px - sl_mult*atr_val if side=="long" else px + sl_mult*atr_val
    tp1 = px + tp1_mult*atr_val if side=="long" else px - tp1_mult*atr_val
    tp2 = px + tp2_mult*atr_val if side=="long" else px - tp2_mult*atr_val

    # איכות (עם עיגון/פקטורים — אופציונלי)
    from utils.anchor import AnchorDecision
    anchor = AnchorDecision(bias="BULLISH" if side=="long" else "BEARISH", score=72.0, mode_applied="composite")
    q = compute_quality(symbol=symbol, side=side.upper(), entry=px, sl=sl, tp=tp1,
                        leverage=10, budget=100, anchor=anchor, atr=atr_val, trades_log_path=None)

    out = {"ok": True, "side": side, "entry": px, "sl": sl, "tp1": tp1, "tp2": tp2,
           "quality": q["quality_score"], "success_pct": q["success_pct"],
           "context": {"lead": lead, "tf": tf}, "indicators": res}

    out["feeds_used"] = {k: True for k in ("delta_per_bar","oi_df","df_spot","df_mark") if feeds.get(k) is not None}

    return out

async def enrich_with_funding(out: Dict[str, Any], *, symbol: str, side: str) -> Dict[str, Any]:
    try:
        fb = await funding_async(symbol, side=side.upper())
        out.setdefault("context",{})["funding"] = fb
    except Exception as e:
        out.setdefault("context",{})["funding_error"] = str(e)
    return out

