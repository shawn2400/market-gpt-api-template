# utils/sop_enforcer.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Dict, Any, Literal, List
import os

from utils.feature_flags import (
    get_flag, FEAT_BTC_GATE, FEAT_TF_ALIGN, FEAT_SPREAD_DEPTH,
    FEAT_MARK_INDEX_SANITY, FEAT_VOLUME_GATE, FEAT_PUMP_NUKE,
    FEAT_QUALITY_ENFORCE
)
from utils.book_gates import gate_spread_depth, gate_mark_index_sanity, gate_pump_nuke, gate_volume_ratio

Side = Literal["LONG","SHORT"]

@dataclass
class SopInputs:
    symbol: str
    side: Side
    interval: str = "15m"
    # מגמת BTC/סימבול (EMA21>EMA50)
    btc_trend_ok: Optional[bool] = None
    sym_trend_ok: Optional[bool] = None
    tf_aligned: Optional[bool] = None   # יישור TF (5m/15m/1h) — אם מחושב בחוץ
    # ספר פקודות
    best_bid: Optional[float] = None
    best_ask: Optional[float] = None
    bid_qty: Optional[float] = None
    ask_qty: Optional[float] = None
    # MARK/INDEX sanity
    mark_price: Optional[float] = None
    index_price: Optional[float] = None
    # תנועה קצרה/ווליום
    delta5m_abs_pct: Optional[float] = None
    volume_ma20_ratio: Optional[float] = None
    # איכות
    quality_score: Optional[float] = None

def _rc(code: str) -> str:
    return code

def enforce(inputs: SopInputs) -> Dict[str, Any]:
    """SOP Enforcer (ללא I/O) — מקבל מטריקות מוכנות, מחזיר ok + reason_code ראשון + רשימת קודים."""
    reasons: List[str] = []

    # 1) מגמת BTC/סימבול + TF Align
    if get_flag(FEAT_BTC_GATE, False):
        if inputs.btc_trend_ok is False:
            reasons.append(_rc("btc_trend_mismatch"))
    if get_flag(FEAT_TF_ALIGN, False):
        if inputs.tf_aligned is False:
            reasons.append(_rc("tf_not_aligned"))
    if get_flag(FEAT_TF_ALIGN, False) or get_flag(FEAT_BTC_GATE, False):
        if inputs.sym_trend_ok is False:
            reasons.append(_rc("symbol_trend_mismatch"))

    # 2) Spread/Depth
    if get_flag(FEAT_SPREAD_DEPTH, False):
        max_spread = float(os.getenv("SOP_MAX_SPREAD_BPS","3.0"))
        min_top_qty = float(os.getenv("SOP_MIN_TOP_QTY","0.0"))
        g = gate_spread_depth(
            best_bid=inputs.best_bid, best_ask=inputs.best_ask,
            bid_qty=inputs.bid_qty, ask_qty=inputs.ask_qty,
            max_spread_bps=max_spread, min_top_qty=min_top_qty
        )
        if not g["ok"]:
            reasons.append(_rc(g["code"]))

    # 3) MARK↔INDEX sanity
    if get_flag(FEAT_MARK_INDEX_SANITY, False):
        gap_bps = float(os.getenv("SOP_MARK_INDEX_MAX_GAP_BPS","20.0"))
        g = gate_mark_index_sanity(mark=inputs.mark_price, index=inputs.index_price, max_gap_bps=gap_bps)
        if not g["ok"]:
            reasons.append(_rc(g["code"]))

    # 4) Pump/Nuke gate
    if get_flag(FEAT_PUMP_NUKE, False):
        thr = float(os.getenv("SOP_PUMP_NUKE_MAX_5M_PCT","1.0"))
        g = gate_pump_nuke(inputs.delta5m_abs_pct, threshold_pct=thr)
        if not g["ok"]:
            reasons.append(_rc(g["code"]))

    # 5) Volume gate
    if get_flag(FEAT_VOLUME_GATE, False):
        minr = float(os.getenv("SOP_VOLUME_MIN_RATIO","1.2"))
        g = gate_volume_ratio(inputs.volume_ma20_ratio, min_ratio=minr)
        if not g["ok"]:
            reasons.append(_rc(g["code"]))

    # 6) Quality
    if get_flag(FEAT_QUALITY_ENFORCE, False):
        qmin = float(os.getenv("QUALITY_MIN_SCORE","8.5"))
        if inputs.quality_score is not None and inputs.quality_score < qmin:
            reasons.append(_rc("quality_low"))

    ok = len(reasons) == 0
    return {"ok": ok, "reason_code": (None if ok else reasons[0]), "reasons": reasons, "symbol": inputs.symbol, "side": inputs.side}

