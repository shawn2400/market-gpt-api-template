# utils/pnl_summary.py
from __future__ import annotations
import json, os, time
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Any, Dict, List, Optional, Tuple, Iterable

TZ = ZoneInfo(os.getenv("TZ", "Asia/Jerusalem"))

_CANDIDATE_FILES = [
    "pnl_tracker.json",
    "data/pnl_tracker.json",
    "trades_log.json",
    "data/trades_log.json",
]

def _load_json_candidates() -> List[Dict[str, Any]]:
    """Load trades-like records from known files. Returns a flat list of dicts."""
    items: List[Dict[str, Any]] = []
    for p in _CANDIDATE_FILES:
        try:
            if not os.path.exists(p):
                continue
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and "items" in data and isinstance(data["items"], list):
                items.extend([x for x in data["items"] if isinstance(x, dict)])
            elif isinstance(data, list):
                items.extend([x for x in data if isinstance(x, dict)])
            elif isinstance(data, dict):
                # pnl_tracker.json might be { "YYYY-MM-DD": { ... } }
                for k, v in data.items():
                    if isinstance(v, dict):
                        v2 = dict(v)
                        v2["_day_key"] = k
                        items.append(v2)
        except Exception:
            # ignore and continue
            continue
    return items

def _parse_ts(rec: Dict[str, Any]) -> Optional[datetime]:
    """Try multiple time fields: closed_at, updated_at, ts, timestamp; supports iso or epoch."""
    keys = ["closed_at", "updated_at", "created_at", "ts", "timestamp", "_day_key"]
    for k in keys:
        val = rec.get(k)
        if val is None:
            continue
        # Try epoch (sec or ms)
        try:
            if isinstance(val, (int, float)):
                # assume seconds; if too large, treat as ms
                if val > 1e12:  # definitely ms
                    dt = datetime.fromtimestamp(val / 1000.0, TZ)
                elif val > 1e10:  # probably ms
                    dt = datetime.fromtimestamp(val / 1000.0, TZ)
                else:
                    dt = datetime.fromtimestamp(val, TZ)
                return dt
        except Exception:
            pass
        # Try ISO strings or YYYY-MM-DD
        if isinstance(val, str):
            s = val.strip()
            # YYYY-MM-DD only → take 23:59 that day to include in group
            if len(s) == 10 and s[4] == "-" and s[7] == "-":
                try:
                    d = datetime.fromisoformat(s)
                    return d.replace(tzinfo=TZ, hour=23, minute=59, second=59)
                except Exception:
                    pass
            try:
                # auto parse ISO
                d = datetime.fromisoformat(s.replace("Z", "+00:00"))
                if d.tzinfo is None:
                    d = d.replace(tzinfo=TZ)
                return d.astimezone(TZ)
            except Exception:
                pass
    return None

def _num(rec: Dict[str, Any], keys: Iterable[str], default: float = 0.0) -> float:
    for k in keys:
        if k in rec and rec[k] is not None:
            try:
                return float(rec[k])
            except Exception:
                continue
    return default

def _side(rec: Dict[str, Any]) -> str:
    s = str(rec.get("side") or rec.get("positionSide") or "").upper()
    return s or "NA"

def _symbol(rec: Dict[str, Any]) -> str:
    s = str(rec.get("symbol") or rec.get("asset") or "").upper()
    return s or "NA"

def _entry(rec: Dict[str, Any]) -> float:
    return _num(rec, ["entry", "entry_price", "entryPrice", "avgEntryPrice"], 0.0)

def _exit(rec: Dict[str, Any]) -> float:
    return _num(rec, ["exit", "exit_price", "exitPrice", "avgExitPrice", "close_price"], 0.0)

def _realized_pnl(rec: Dict[str, Any]) -> float:
    return _num(rec, ["realized_pnl", "realizedPnl", "pnl", "profit_usd", "net_pnl_usd"], 0.0)

def _day_key(dt: datetime) -> str:
    return dt.astimezone(TZ).strftime("%Y-%m-%d")

def get_pnl_summary(limit_days: int = 30) -> Dict[str, Any]:
    """
    Compute PnL summary for the last <limit_days> days (TZ-aware).
    Returns schema:
    {
      "total_trades": int,
      "realized_pnl_usd": float,
      "win_rate": float [0..100],
      "days": [{"day": "YYYY-MM-DD", "count": int, "pnl": float}],
      "symbols": [{"symbol": "BTCUSDT", "count": int, "pnl": float}],
      "sampled_days": int,
      "source_files_checked": [...],
      "note": str
    }
    """
    items = _load_json_candidates()
    if not items:
        return {
            "total_trades": 0,
            "realized_pnl_usd": 0.0,
            "win_rate": 0.0,
            "days": [],
            "symbols": [],
            "sampled_days": limit_days,
            "source_files_checked": _CANDIDATE_FILES,
            "note": "no data files found",
        }

    now = datetime.now(TZ)
    cutoff = now - timedelta(days=max(1, int(limit_days)))

    # normalize & filter
    norm: List[Dict[str, Any]] = []
    for rec in items:
        dt = _parse_ts(rec) or now
        if dt < cutoff:
            continue
        pnl = _realized_pnl(rec)
        norm.append({
            "symbol": _symbol(rec),
            "side": _side(rec),
            "entry_price": _entry(rec),
            "exit_price": _exit(rec),
            "pnl": pnl,
            "ts": dt,
        })

    total = len(norm)
    if total == 0:
        return {
            "total_trades": 0,
            "realized_pnl_usd": 0.0,
            "win_rate": 0.0,
            "days": [],
            "symbols": [],
            "sampled_days": limit_days,
            "source_files_checked": _CANDIDATE_FILES,
            "note": "no trades in time window",
        }

    # aggregates
    realized = sum(x["pnl"] for x in norm)
    wins = sum(1 for x in norm if x["pnl"] > 0)
    win_rate = 100.0 * wins / total if total > 0 else 0.0

    # by day
    agg_days: Dict[str, Dict[str, Any]] = {}
    for x in norm:
        d = _day_key(x["ts"])
        a = agg_days.setdefault(d, {"day": d, "count": 0, "pnl": 0.0})
        a["count"] += 1
        a["pnl"] += float(x["pnl"])

    # by symbol
    agg_sym: Dict[str, Dict[str, Any]] = {}
    for x in norm:
        s = x["symbol"]
        a = agg_sym.setdefault(s, {"symbol": s, "count": 0, "pnl": 0.0})
        a["count"] += 1
        a["pnl"] += float(x["pnl"])

    days_list = sorted(agg_days.values(), key=lambda z: z["day"])
    symbols_list = sorted(agg_sym.values(), key=lambda z: (-z["pnl"], z["symbol"]))

    return {
        "total_trades": total,
        "realized_pnl_usd": float(realized),
        "win_rate": float(win_rate),
        "days": days_list,
        "symbols": symbols_list,
        "sampled_days": int(limit_days),
        "source_files_checked": _CANDIDATE_FILES,
        "note": "computed from available local JSON files",
    }

# Optional helper kept for backwards compatibility with drafts you shared
def summarize_trades(trades: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Normalize a given list of trades to a minimal schema (no pandas)."""
    out: List[Dict[str, Any]] = []
    for rec in trades or []:
        out.append({
            "symbol": _symbol(rec),
            "side": _side(rec),
            "entry_price": _entry(rec),
            "exit_price": _exit(rec),
            "pnl": _realized_pnl(rec),
            "timestamp": (_parse_ts(rec) or datetime.now(TZ)).isoformat(),
        })
    return out



