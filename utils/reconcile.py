# utils/reconcile.py
from __future__ import annotations
import asyncio, logging, os, time
from typing import Dict, Any, List, Optional

from utils.grid_manager import ensure_grid_for as grid_ensure, reconcile as grid_reconcile
from utils.binance_client import futures_position_risk, get_open_orders, cancel_order
from utils.open_trade_manager import manage_open_trades

logger = logging.getLogger("algogpt.reconcile")

def _side_to_close(side: str) -> str:
    return "SELL" if (side or "").upper() in ("LONG","BUY") else "BUY"

def _list_open_symbols() -> List[str]:
    syms = []
    try:
        for p in futures_position_risk() or []:
            amt = float(p.get("positionAmt") or 0.0)
            if abs(amt) > 0:
                syms.append(str(p.get("symbol") or "").upper())
    except Exception as e:
        logger.warning({"event":"reconcile_list_pos_failed","err":str(e)})
    # סדר ייחודי ושימור קדימות BTCUSDT אם קיים
    seen, out = set(), []
    if "BTCUSDT" in syms: out.append("BTCUSDT"); seen.add("BTCUSDT")
    for s in syms:
        s = s.upper()
        if s not in seen:
            out.append(s); seen.add(s)
    return out

def _find_sl_orders(symbol: str) -> List[Dict[str, Any]]:
    try:
        oo = get_open_orders(symbol) or []
    except Exception:
        oo = []
    sls = []
    for o in oo:
        ty = str(o.get("type","")).upper()
        ro = str(o.get("reduceOnly","")).lower() in ("true","1")
        if ro and ty in ("STOP","STOP_MARKET","STOP_LOSS","STOP_LOSS_LIMIT"):
            sls.append(o)
    return sls

def _keep_one_sl(symbol: str) -> Optional[str]:
    """שומר בדיוק SL אחד (אם יש כפילות – מבטל את העודפים). מחזיר summary קצר."""
    sls = _find_sl_orders(symbol)
    if len(sls) <= 1:
        return None
    # שמר את ה"מחמיר" יותר:
    # LONG → נשמור את ה-SL הנמוך ביותר; SHORT → הגבוה ביותר (הסקה מהשם בצד ה-close לא זמינה כאן)
    # אם יש לנו clientOrderId עם 'SHORT'/'LONG' אפשר לשכלל; נלך כללית:
    try:
        prices = [float(o.get("stopPrice") or o.get("price") or 0.0) for o in sls]
        # נשמור את הקיצון (מקס' הגנה): המינימום
        keep_idx = prices.index(min(prices))
    except Exception:
        keep_idx = 0
    keep_id = sls[keep_idx].get("orderId")
    removed = []
    for i, o in enumerate(sls):
        if i == keep_idx:
            continue
        try:
            cancel_order(symbol, o.get("orderId"))
            removed.append(str(o.get("orderId")))
        except Exception as e:
            logger.warning({"event":"reconcile_cancel_extra_sl_failed","symbol":symbol,"err":str(e)})
    return f"kept={keep_id}, canceled={','.join(removed)}" if removed else None

async def reconcile_symbol(symbol: str) -> Dict[str, Any]:
    symbol = (symbol or "").upper().strip()
    steps = []

    # 1) ודא גריד/TP/SL בסיסי (idempotent)
    try:
        r = await grid_ensure(symbol)
        steps.append({"grid_ensure": r})
    except Exception as e:
        steps.append({"grid_ensure_error": str(e)})

    # 2) שחזור TP חסרים אם יש סטייט (idempotent)
    try:
        r2 = await grid_reconcile(symbol)
        steps.append({"grid_reconcile": r2})
    except Exception as e:
        steps.append({"grid_reconcile_error": str(e)})

    # 3) ודא SL יחיד
    kept = _keep_one_sl(symbol)
    if kept:
        steps.append({"single_sl": kept})

    return {"symbol": symbol, "steps": steps}

async def reconcile_after_restart(sleep_first: float = 2.0) -> Dict[str, Any]:
    """
    מריץ סנכרון עדין פעם אחת אחרי עליית השרת:
    - השהייה קצרה כדי לא להעמיס בעלייה.
    - סריקה סימבולים עם פוזיציה → reconcile_symbol.
    - קריאה ל-manage_open_trades בסוף (עדכון SL/TP אם צריך).
    """
    await asyncio.sleep(max(0.0, sleep_first))
    syms = _list_open_symbols()
    details = []
    for s in syms:
        try:
            d = await reconcile_symbol(s)
            details.append(d)
            await asyncio.sleep(0.12)  # מניעת burst
        except Exception as e:
            details.append({"symbol": s, "error": str(e)})
    try:
        _ = await manage_open_trades()
    except Exception as e:
        details.append({"manage_open_trades_error": str(e)})
    return {"ok": True, "symbols": syms, "details": details}
