# utils/account_state.py
from __future__ import annotations
from typing import Dict, Any, Iterable, Optional
import math

try:
    from utils.binance_futures import BinanceFutures  # type: ignore
except Exception:
    BinanceFutures = None  # type: ignore

class _MissingClient(RuntimeError): ...

async def _client() -> "BinanceFutures":
    if BinanceFutures is None:
        raise _MissingClient("BinanceFutures client missing; add utils/binance_futures.py")
    return BinanceFutures()

def _norm_float(x) -> float:
    try:
        return float(x)
    except:
        return 0.0

def _side_from_amt(amt: float) -> str:
    if amt > 0: return "LONG"
    if amt < 0: return "SHORT"
    return "NEUTRAL"

async def get_positions_snapshot(symbols: Optional[Iterable[str]] = None) -> Dict[str, Dict[str, Any]]:
    """
    מחזיר מילון {symbol: {...}} על כל הפוזיציות (כולל qty, side, entry, leverage, pnl).
    אם symbols=None → מחזיר הכל; אחרת יסנן רק את הסימבולים שביקשת.
    מצופה לעבוד עם account/positionRisk של בינאנס (נורמליזציה בלקוח).
    """
    cli = await _client()
    raw_positions = await cli.get_positions()  # רשימת dict-ים לכל סימבול
    out: Dict[str, Dict[str, Any]] = {}
    syset = set([s.upper() for s in symbols]) if symbols else None

    for p in raw_positions or []:
        sym = str(p.get("symbol") or "").upper()
        if not sym:
            continue
        if syset and sym not in syset:
            continue
        amt = _norm_float(p.get("positionAmt"))
        entry = _norm_float(p.get("entryPrice"))
        lev = int(_norm_float(p.get("leverage")) or 0)
        upl = _norm_float(p.get("unrealizedProfit"))
        mark = _norm_float(p.get("markPrice")) if p.get("markPrice") is not None else 0.0

        # אפשרות: לחשב pnl% אם יש מרק והכניסה
        pnl_pct = 0.0
        if entry > 0 and mark > 0 and amt != 0:
            if amt > 0:
                pnl_pct = (mark - entry) / entry * 100.0
            else:
                pnl_pct = (entry - mark) / entry * 100.0

        out[sym] = {
            "symbol": sym,
            "qty": amt,                 # >0 long, <0 short
            "side": _side_from_amt(amt),
            "entry_price": entry,
            "mark_price": mark,
            "leverage": lev,
            "unrealized_pnl": upl,
            "unrealized_pnl_pct": pnl_pct,
            "isolated": bool(str(p.get("isolated") or p.get("isolatedMargin") or "false").lower()=="true"),
            "raw": p,
        }
    return out
