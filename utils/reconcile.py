# utils/reconcile.py
from __future__ import annotations

import os
import json
import time
import asyncio
import logging
from typing import Any, Dict, List, Set, Optional

logger = logging.getLogger("algogpt.reconcile")

def _as_bool(s: Optional[str], default: bool = False) -> bool:
    return str(s).strip().lower() in {"1","true","yes","on"} if s is not None else default

def _as_int(s: Optional[str], default: int) -> int:
    try: return int(str(s).strip())
    except Exception: return default

GRID_STATE_TTL_SEC = _as_int(os.getenv("GRID_STATE_CLEANUP_TTL_SEC", "86400"), 86400)  # ברירת מחדל: יום

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────
def _open_position_symbols() -> Set[str]:
    """
    מחזיר קבוצה של סימבולים עם positionAmt != 0 לפי futures_position_risk.
    """
    from utils.binance_client import futures_position_risk
    out: Set[str] = set()
    try:
        for p in futures_position_risk() or []:
            try:
                sym = str(p.get("symbol") or "").upper()
                amt = float(p.get("positionAmt") or 0.0)
                if sym and abs(amt) > 0:
                    out.add(sym)
            except Exception:
                continue
    except Exception as e:
        logger.warning({"event":"open_position_symbols_failed","error":str(e)})
    return out

def _list_grid_state_symbols() -> List[str]:
    """
    מנסה להחזיר את כל הסימבולים עם סטייט גריד (Redis hkeys + זיכרון פנימי).
    """
    syms: Set[str] = set()
    try:
        import utils.grid_manager as gm
        # Redis
        try:
            if getattr(gm, "_redis", None) and getattr(gm, "RKEY", None):
                for s in gm._redis.hkeys(gm.RKEY) or []:
                    if s: syms.add(str(s).upper())
        except Exception:
            pass
        # זיכרון פנימי
        try:
            for s in (getattr(gm, "_mem", {}) or {}).keys():
                if s: syms.add(str(s).upper())
        except Exception:
            pass
    except Exception as e:
        logger.warning({"event":"list_grid_state_failed","error":str(e)})
    return sorted(syms)

def _state_timestamp_for(sym: str) -> Optional[float]:
    """
    מאתר timestamp של הסטייט (ts/created) אם קיים (Redis או זיכרון).
    """
    try:
        import utils.grid_manager as gm
        # Redis קודם
        try:
            if getattr(gm, "_redis", None) and getattr(gm, "RKEY", None):
                raw = gm._redis.hget(gm.RKEY, sym.upper())
                if raw:
                    try:
                        st = json.loads(raw)
                        ts = float(st.get("ts") or st.get("created") or 0.0)
                        return ts if ts > 0 else None
                    except Exception:
                        pass
        except Exception:
            pass
        # זיכרון פנימי
        try:
            st = (getattr(gm, "_mem", {}) or {}).get(sym.upper())
            if st:
                ts = float(st.get("ts") or st.get("created") or 0.0)
                return ts if ts > 0 else None
        except Exception:
            pass
    except Exception:
        pass
    return None

# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────
async def reconcile_symbol(symbol: str) -> Dict[str, Any]:
    """
    ensure_grid_for(symbol): אם אין סטייט נתחיל גריד לפוזיציה קיימת; אם יש — נעשה reconcile קל.
    """
    import utils.grid_manager as gm
    s = (symbol or "").upper().strip()
    try:
        res = await gm.ensure_grid_for(s)
        # normalizing structure
        ok = bool(res.get("ok", True))
        restored = res.get("restored")
        errors = res.get("errors") if isinstance(res.get("errors"), list) else []
        return {"symbol": s, "ok": ok, "restored": restored, "errors": errors}
    except Exception as e:
        logger.warning({"event":"reconcile_symbol_failed","symbol":s,"error":str(e)})
        return {"symbol": s, "ok": False, "error": str(e)}

async def cleanup_orphan_states(open_syms: Optional[Set[str]] = None, *, max_age_sec: Optional[int] = None) -> int:
    """
    מנקה סטייט גריד ל'סימבולים יתומים' — יש סטייט אבל אין פוזיציה.
    מכבד TTL (ברירת מחדל 24ש').
    """
    import utils.grid_manager as gm
    if open_syms is None:
        open_syms = _open_position_symbols()
    ttl = int(max_age_sec if max_age_sec is not None else GRID_STATE_TTL_SEC)
    now = time.time()

    candidates = [s for s in _list_grid_state_symbols() if s not in open_syms]
    to_delete: List[str] = []
    for s in candidates:
        ts = _state_timestamp_for(s)
        if (ts is None) or (now - ts >= ttl):
            to_delete.append(s)

    if not to_delete:
        return 0

    # ביצוע ביטול הזמנות RO (אם יש) וניקוי סטייט
    done = 0
    async def _cancel_and_drop(sym: str) -> None:
        nonlocal done
        try:
            # זהירות: cancel_grid לא סוגר פוזיציה, רק מבטל הזמנות וניקה סטייט
            await gm.cancel_grid(sym)
            done += 1
        except Exception as e:
            logger.warning({"event":"cleanup_cancel_failed","symbol":sym,"error":str(e)})

    await asyncio.gather(*[_cancel_and_drop(s) for s in to_delete])
    return done

async def reconcile_after_restart(*, sleep_first: float = 0.0) -> Dict[str, Any]:
    """
    ריצה עדינה לאחר ריסטארט:
      1) לוקח את כל הפוזיציות הפתוחות → ensure_grid_for עבור כל סימבול.
      2) מנקה סטייט יתום ישן (כפוף ל-TTL).
    """
    if sleep_first and sleep_first > 0:
        await asyncio.sleep(min(10.0, float(sleep_first)))

    open_syms = _open_position_symbols()
    results: List[Dict[str, Any]] = []

    # Recon לכל סימבול עם פוזיציה
    for s in sorted(open_syms):
        r = await reconcile_symbol(s)
        results.append(r)

    # ניקוי סטייט ישן ללא פוזיציה
    cleaned = 0
    try:
        cleaned = await cleanup_orphan_states(open_syms=open_syms)
    except Exception as e:
        logger.warning({"event":"cleanup_orphan_failed","error":str(e)})

    return {
        "ok": True,
        "total_positions": len(open_syms),
        "cleaned_orphan_states": cleaned,
        "results": results,
    }

__all__ = [
    "reconcile_symbol",
    "reconcile_after_restart",
    "cleanup_orphan_states",
]

