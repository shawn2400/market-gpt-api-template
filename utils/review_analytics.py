# utils/review_analytics.py
from __future__ import annotations
import os, json, time
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional
from collections import defaultdict

_LOG_PATH = Path(os.getenv("TRADES_LOG_PATH", "data/trades_log.json"))

# פורמטים נתמכים בקובץ (JSON Lines):
# {"ts": 1711111111, "symbol":"BTCUSDT", "event":"OPEN"|"CLOSE"|"BE_SET"|"SL_HIT"|"TP1_FILLED"|"TP2_FILLED", "trade_id":"<id>"}
# אם אין trade_id: ננסה לשרשר לפי symbol+חלון זמן (היוריסטיקה עדינה).

def _iter_records(days: int) -> List[Dict[str, Any]]:
    if not _LOG_PATH.exists():
        return []
    cutoff = time.time() - (days * 86400)
    out: List[Dict[str, Any]] = []
    with _LOG_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line: continue
            try:
                rec = json.loads(line)
                ts = float(rec.get("ts") or rec.get("time") or 0.0)
                if ts and ts >= cutoff:
                    out.append(rec)
            except Exception:
                continue
    return out

def _group_by_trade(records: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    trades: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in records:
        tid = r.get("trade_id")
        if not tid:
            # fallback key: symbol + rounded hour bucket
            sym = (r.get("symbol") or "UNK").upper()
            bucket = int((float(r.get("ts") or time.time())) // 3600)
            tid = f"{sym}:{bucket}"
        trades[str(tid)].append(r)
    return trades

def compute_analytics(days: int = 7) -> Dict[str, Any]:
    recs = _iter_records(days)
    trades = _group_by_trade(recs)

    be_count = 0
    be_to_sl = 0
    tp1 = 0
    tp1_to_tp2 = 0
    durations: List[float] = []  # seconds

    for tid, evs in trades.items():
        evs = sorted(evs, key=lambda x: float(x.get("ts") or 0.0))
        has_be = any((e.get("event") or "").upper() in ("BE_SET","BREAKEVEN") for e in evs)
        sl_hit = any((e.get("event") or "").upper() in ("SL_HIT","STOP_HIT","STOP") for e in evs)
        t1 = any((e.get("event") or "").upper() in ("TP1_FILLED","TP1") for e in evs)
        t2 = any((e.get("event") or "").upper() in ("TP2_FILLED","TP2") for e in evs)

        if has_be:
            be_count += 1
            if sl_hit:
                be_to_sl += 1
        if t1:
            tp1 += 1
            if t2:
                tp1_to_tp2 += 1

        # זמן בפוזיציה: OPEN → CLOSE
        open_ts = next((float(e.get("ts")) for e in evs if (e.get("event") or "").upper() == "OPEN"), None)
        close_ts = next((float(e.get("ts")) for e in evs if (e.get("event") or "").upper() == "CLOSE"), None)
        if open_ts and close_ts and close_ts > open_ts:
            durations.append(close_ts - open_ts)

    ratio_be_sl = (be_to_sl / be_count) if be_count else 0.0
    ratio_t1_t2 = (tp1_to_tp2 / tp1) if tp1 else 0.0
    avg_min = (sum(durations)/len(durations)/60.0) if durations else 0.0

    return {
        "window_days": days,
        "counts": {
            "trades_grouped": len(trades),
            "breakeven_total": be_count,
            "breakeven_to_sl": be_to_sl,
            "tp1_total": tp1,
            "tp1_to_tp2": tp1_to_tp2,
        },
        "ratios": {
            "be_to_sl": round(ratio_be_sl, 4),
            "tp1_to_tp2": round(ratio_t1_t2, 4),
        },
        "avg_position_minutes": round(avg_min, 2),
    }
