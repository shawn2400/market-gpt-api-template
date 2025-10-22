# utils/account_state.py
from __future__ import annotations
from typing import List, Dict, Any, Iterable, Optional

try:
    from utils.binance_futures_exec import BinanceFuturesExec  # type: ignore
except Exception:
    BinanceFuturesExec = None  # type: ignore

class _MissingClient(RuntimeError): ...

def _cli() -> "BinanceFuturesExec":
    if BinanceFuturesExec is None:
        raise _MissingClient("BinanceFuturesExec missing; add utils/binance_futures_exec.py")
    return BinanceFuturesExec()

def _f(x) -> float:
    try: return float(x)
    except: return 0.0

def _side_from_amt(a: float) -> str:
    if a > 0:  return "LONG"
    if a < 0:  return "SHORT"
    return "NEUTRAL"

async def get_positions_snapshot(symbols: Optional[Iterable[str]] = None) -> List[Dict[str, Any]]:
    """
    מחזיר רשימה של פוזיציות מנורמלות:
      [{"symbol","positionAmt","entryPrice","markPrice","leverage","unrealizedProfit","unrealized_pnl_pct","side","isolated","raw"}...]
    אם symbols!=None — יסנן רק אותן.
    """
    cli = _cli()
    syset = set([s.upper() for s in symbols]) if symbols else None
    raw = cli.get_positions()
    out: List[Dict[str, Any]] = []
    for p in raw or []:
        sym = str(p.get("symbol") or "").upper()
        if not sym:
            continue
        if syset and sym not in syset:
            continue
        amt = _f(p.get("positionAmt"))
        entry = _f(p.get("entryPrice"))
        mark = _f(p.get("markPrice"))
        upl  = _f(p.get("unrealizedProfit") or p.get("unRealizedProfit"))
        lev  = int(_f(p.get("leverage")))
        pnl_pct = 0.0
        if entry > 0 and mark > 0 and amt != 0:
            pnl_pct = ((mark - entry)/entry*100.0) if amt > 0 else ((entry - mark)/entry*100.0)
        out.append({
            "symbol": sym,
            "positionAmt": amt,
            "entryPrice": entry,
            "markPrice": mark,
            "leverage": lev,
            "unrealizedProfit": upl,
            "unrealized_pnl_pct": pnl_pct,
            "side": _side_from_amt(amt),
            "isolated": bool(str(p.get("isolated","false")).lower()=="true"),
            "raw": p,
        })
    return out

