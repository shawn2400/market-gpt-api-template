# utils/reconcile.py
from __future__ import annotations

import os
import json
import time
import asyncio
import logging
from typing import Any, Dict, List, Set, Optional

from utils.alerts import tg_rec  # ← חדש

logger = logging.getLogger("algogpt.reconcile")

def _as_bool(s: Optional[str], default: bool = False) -> bool:
    return str(s).strip().lower() in {"1","true","yes","on"} if s is not None else default

def _as_int(s: Optional[str], default: int) -> int:
    try: return int(str(s).strip())
    except Exception: return default

GRID_STATE_CLEANUP_TTL_SEC = _as_int(os.getenv("GRID_STATE_CLEANUP_TTL_SEC", "86400"), 86400)

def _open_position_symbols() -> Set[str]:
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
    syms: Set[str] = set()
    try:
        import utils.grid_manager as gm
        try:
            if getattr(gm, "_redis", None) and getattr(gm, "RKEY", None):
                for s in gm._redis.hkeys(gm.RKEY) or []:
                    if s: syms.add(str(s).upper())
        except Exception:
            pass
        try:
            for s in (getattr(gm, "_mem", {}) or {}).keys():
                if s: syms.add(str(s).upper())
        except Exception:
            pass
    except Exception as e:
        logger.warning({"event":"list_grid_state_failed","error":str(e)})
    return sorted(syms)

def _state_timestamp_for(sym: str) -> Optional[float]:
    try:
        import utils.grid_manager as gm
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

async def reconcile_symbol(symbol: str) -> Dict[str, Any]:
    import utils.grid_manager as gm
    s = (symbol or "").upper().strip()
    try:
        res = await gm.ensure_grid_for(s)
        ok = bool(res.get("ok", True))
        restored = res.get("restored")
        errors = res.get("errors") if isinstance(res.get("errors"), list) else []
        # חיווי קצר לטלגרם
        try:
            if ok:
                tg_rec(f"Reconcile • {s} • ok (restored={restored})")
            else:
                tg_rec(f"Reconcile • {s} • error: {res.get('error')}")
        except Exception:
            pass
        return {"symbol": s, "ok": ok, "restored": restored, "errors": errors}
    except Exception as e:
        logger.warning({"event":"reconcile_symbol_failed","symbol":s,"error":str(e)})
        try: tg_rec(f"Reconcile • {s} • error: {e}")
        except Exception: pass
        return {"symbol": s, "ok": False, "error": str(e)}

async def cleanup_orphan_states(open_syms: Optional[Set[str]] = None, *, max_age_sec: Optional[int] = None) -> int:
    import utils.grid_manager as gm
    if open_syms is None:
        open_syms = _open_position_symbols()
    ttl = int(max_age_sec if max_age_sec is not None else GRID_STATE_CLEANUP_TTL_SEC)
    now = time.time()

    candidates = [s for s in _list_grid_state_symbols() if s not in open_syms]
    to_delete: List[str] = []
    for s in candidates:
        ts = _state_timestamp_for(s)
        if (ts is None) or (now - ts >= ttl):
            to_delete.append(s)

    if not to_delete:
        return 0

    done = 0
    async def _cancel_and_drop(sym: str) -> None:
        nonlocal done
        try:
            await gm.cancel_grid(sym)
            done += 1
        except Exception as e:
            logger.warning({"event":"cleanup_cancel_failed","symbol":sym,"error":str(e)})

    await asyncio.gather(*[_cancel_and_drop(s) for s in to_delete])
    return done

async def reconcile_after_restart(*, sleep_first: float = 0.0) -> Dict[str, Any]:
    if sleep_first and sleep_first > 0:
        await asyncio.sleep(min(10.0, float(sleep_first)))

    open_syms = _open_position_symbols()
    results: List[Dict[str, Any]] = []

    for s in sorted(open_syms):
        r = await reconcile_symbol(s)
        results.append(r)

    cleaned = 0
    try:
        cleaned = await cleanup_orphan_states(open_syms=open_syms)
    except Exception as e:
        logger.warning({"event":"cleanup_orphan_failed","error":str(e)})

    # סיכום לטלגרם
    try:
        ok_cnt = sum(1 for r in results if r.get("ok"))
        err_cnt = sum(1 for r in results if not r.get("ok"))
        touched = ", ".join(sorted({r.get("symbol","?") for r in results})) or "-"
        tg_rec(f"Reconcile done • positions={len(open_syms)} • ok={ok_cnt} • errors={err_cnt} • cleaned={cleaned}\n{touched}")
    except Exception:
        pass

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


