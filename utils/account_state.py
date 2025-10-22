# utils/account_state.py
from __future__ import annotations
from typing import Any, Dict, List
from utils.binance_futures_exec import BinanceFuturesExec

_EXEC = None

def _cli() -> BinanceFuturesExec:
    global _EXEC
    if _EXEC is None:
        _EXEC = BinanceFuturesExec()
    return _EXEC

async def get_positions_snapshot() -> List[Dict[str, Any]]:
    """
    מחזיר רשימת פוזיציות פעילות מ-Binance Futures (PositionRisk).
    רק פוזיציות עם positionAmt != 0 יוחזרו.
    """
    data = _cli().get("/fapi/v2/positionRisk", {}, signed=True)
    out: List[Dict[str, Any]] = []
    for row in data or []:
        try:
            amt = float(row.get("positionAmt") or 0.0)
            if abs(amt) > 0.0:
                out.append({
                    "symbol": str(row.get("symbol") or "").upper(),
                    "positionAmt": amt,
                    "entryPrice": float(row.get("entryPrice") or 0.0),
                    "leverage": int(float(row.get("leverage") or 0)),
                    "unRealizedProfit": float(row.get("unRealizedProfit") or 0.0),
                    "markPrice": float(row.get("markPrice") or 0.0),
                    "isolated": str(row.get("isolated") or "").lower() == "true",
                    "marginType": str(row.get("marginType") or "cross").upper(),
                    "updateTime": int(row.get("updateTime") or 0),
                })
        except Exception:
            pass
    return out


