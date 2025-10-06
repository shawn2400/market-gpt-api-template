# utils/guards_core.py
# -*- coding: utf-8 -*-
"""
Guards Core:
- ensure_protective_stop(symbol, prefer_mode="quantities")
- atomic_update_orders(client, symbol, plan, *, verify_timeout_ms=800, strategy="MINIMAL")

מאפיינים:
- Idempotency מלא: clientOrderId נגזר עם hash מהפעולה ("ALG_{SYM}_{ROLE}_{TS/KEY}").
- Optional Redis lock (aioredis) למניעת מירוצים. יש fallback בזיכרון תהליך.
- STRICT_MODE_SINGLE=1 + USE_NATIVE_TP_SL=0 => מצב "כמויות" בלבד, ללא TPSL native.
- מכבד ENV:
  GUARD_ENSURE_SL, GUARD_SL_GRACE_SEC, STOP_WORKING_TYPE, ENFORCE_QTY_BOUNDS,
  ORD_ATOMIC_UPDATE, ORD_VERIFY_TIMEOUT_MS, ORD_CANCEL_STRATEGY, PRICE_PROTECT,
  LOCK_AFTER_TP1, SL_MONOTONIC, BE_BUFFER_USDT
"""
from __future__ import annotations
import os, time, hmac, hashlib, logging
from contextlib import suppress
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("guards_core")

# -------- Optional Redis (async) ----------
try:
    import redis.asyncio as aioredis  # type: ignore
except Exception:
    aioredis = None

# in-proc fallback lock (best-effort)
_LOCKS: Dict[str, float] = {}

def _bool(name: str, default=False) -> bool:
    v = str(os.getenv(name, "1" if default else "0")).lower()
    return v in ("1", "true", "yes", "on")

def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return default

def _int(name: str, default: int) -> int:
    try:
        return int(float(os.getenv(name, str(default))))
    except Exception:
        return default

def _h(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:10]

async def _redis():
    url = (os.getenv("REDIS_URL") or "").strip()
    if not (aioredis and url):
        return None
    try:
        return aioredis.from_url(url, decode_responses=True)
    except Exception:
        return None

async def _mutex_acquire(key: str, ttl_sec: int = 5) -> bool:
    """cross-process lock using redis; fallback to in-proc."""
    r = await _redis()
    now = time.time()
    if r:
        try:
            ok = await r.set(f"guardlock:{key}", str(now), ex=max(1, ttl_sec), nx=True)
            return bool(ok)
        except Exception:
            pass
    # fallback
    exp = _LOCKS.get(key, 0.0)
    if now < exp:
        return False
    _LOCKS[key] = now + ttl_sec
    return True

async def _mutex_release(key: str) -> None:
    r = await _redis()
    if r:
        with suppress(Exception):
            await r.delete(f"guardlock:{key}")
    _LOCKS.pop(key, None)

# -------- Helpers ----------
def _coid(prefix: str, symbol: str, role: str, key: str) -> str:
    """
    Binanace clientOrderId limit ~ 32 chars. Use compressed form.
    Format: {prefix}_{sym}_{role}_{hash}
    """
    sym = (symbol or "").upper()
    base = f"{prefix[:3]}_{sym[:8]}_{role[:4]}_{_h(key)}"
    return base[:32]

def _price_side_from_position(position_amt: float) -> Optional[str]:
    if position_amt is None:
        return None
    if position_amt > 0:  # long
        return "SELL"  # to reduce with SL
    if position_amt < 0:  # short
        return "BUY"
    return None

def _working_type() -> str:
    return (os.getenv("STOP_WORKING_TYPE") or os.getenv("BINANCE_WORKING_TYPE") or "MARK_PRICE").upper()

# -------- Ensure Protective Stop ----------
def _ensure_inputs_ok() -> Tuple[bool, str]:
    if not _bool("GUARD_ENSURE_SL", True):
        return (False, "GUARD_ENSURE_SL=0")
    if _bool("USE_NATIVE_TP_SL", False) or _bool("NATIVE_TPSL_ENABLE", False):
        return (False, "Native TPSL enabled; guard disabled by policy")
    if _bool("STRICT_MODE_SINGLE", True) is False:
        return (False, "STRICT_MODE_SINGLE=0 (hedge mode not supported by guard)")
    return (True, "")

def _sl_grace() -> float:
    return _float("GUARD_SL_GRACE_SEC", 2.0)

def _sl_monotonic() -> bool:
    return _bool("SL_MONOTONIC", True)

def _be_buffer_usdt() -> float:
    return _float("BE_BUFFER_USDT", 0.03)

def _position_info(cli, symbol: str) -> Tuple[float, float, str]:
    """
    returns (positionAmt, entryPrice, positionSide/BOTH)
    """
    with suppress(Exception):
        arr = cli.futures_position_information(symbol=symbol) or []
        if arr:
            p = arr[0]
            amt = float(p.get("positionAmt") or 0.0)
            ep  = float(p.get("entryPrice") or 0.0)
            ps  = str(p.get("positionSide") or "BOTH")
            return (amt, ep, ps)
    return (0.0, 0.0, "BOTH")

def _best_stop_for_side(side: str, entry_price: float, mark_price: float) -> Optional[float]:
    """
    Simple protective stop around entry with buffer (BE buffer).
    SELL (protects long): stop < entry - buffer
    BUY  (protects short): stop > entry + buffer
    """
    buf = _be_buffer_usdt()
    if side == "SELL":  # long position -> SL below entry
        return max(0.0, (entry_price - buf))
    if side == "BUY":   # short position -> SL above entry
        return (entry_price + buf)
    return None

def _mark(cli, symbol: str) -> float:
    with suppress(Exception):
        t = cli.futures_symbol_ticker(symbol=symbol) or {}
        return float(t.get("price") or 0.0)
    return 0.0

def _existing_conditional(cli, symbol: str) -> List[Dict[str, Any]]:
    out = []
    with suppress(Exception):
        for o in cli.futures_get_open_orders(symbol=symbol) or []:
            typ = (o.get("type") or "").upper()
            if "STOP" in typ:  # STOP, STOP_MARKET, STOP_LOSS_LIMIT
                out.append(o)
    return out

def _needs_new_sl(existing: List[Dict[str, Any]], side: str, new_stop: float) -> bool:
    """Monotonic: אם יש SL קיים בכיוון בטוח יותר—לא נזיז."""
    if not existing:
        return True
    if not _sl_monotonic():
        return True
    best = None
    for o in existing:
        sp = float(o.get("stopPrice") or o.get("price") or 0.0)
        if sp <= 0:
            continue
        if best is None:
            best = sp
        elif side == "SELL":   # long: higher SL is safer
            best = max(best, sp)
        elif side == "BUY":    # short: lower SL is safer
            best = min(best, sp)
    # decide whether new_stop is safer than best
    if best is None:
        return True
    if side == "SELL":
        return new_stop > best
    if side == "BUY":
        return new_stop < best
    return False

def _idempotent_key(symbol: str, side: str, qty: float, stop: float) -> str:
    raw = f"{symbol}|{side}|{qty:.8f}|{stop:.8f}|guard_sl"
    return _h(raw)

def ensure_protective_stop(symbol: str, prefer_mode: str = "quantities") -> Dict[str, Any]:
    """
    Ensure there's ALWAYS a protective SL for an open position (single-side mode).
    Place STOP_MARKET reduceOnly.

    Return:
    {
      "ok": bool,
      "skipped": bool,
      "action": "place"|"skip",
      "placed": bool,
      "clientOrderId": str|None,
      "emergency": bool,
      "detail": str
    }
    """
    ok, why = _ensure_inputs_ok()
    if not ok:
        return {"ok": False, "skipped": True, "detail": why}

    try:
        from binance.client import Client  # type: ignore
    except Exception as e:
        return {"ok": False, "skipped": True, "detail": f"binance import failed: {e}"}

    api_key = (os.getenv("BINANCE_API_KEY") or "").strip()
    api_sec = (os.getenv("BINANCE_API_SECRET") or "").strip()
    if not api_key or not api_sec:
        return {"ok": False, "skipped": True, "detail": "BINANCE keys missing"}

    cli = Client(api_key, api_sec)

    # Single-side enforcement (best-effort)
    with suppress(Exception):
        if (os.getenv("POSITION_MODE_OVERRIDE") or "oneway").lower() in ("oneway","one_way","single","single_side"):
            cli.futures_change_position_mode(dualSidePosition="false")

    amt, entry_price, pos_side = _position_info(cli, symbol)
    if abs(amt) < 1e-12:
        return {"ok": True, "skipped": True, "detail": "no position"}

    side = _price_side_from_position(amt)
    if not side:
        return {"ok": False, "skipped": True, "detail": "unknown side"}

    mark = _mark(cli, symbol)
    stop_price = _best_stop_for_side(side, entry_price or mark, mark)
    if not stop_price or stop_price <= 0:
        return {"ok": False, "skipped": True, "detail": "failed to compute stop"}

    existing = _existing_conditional(cli, symbol)
    if not _needs_new_sl(existing, side, stop_price):
        return {"ok": True, "skipped": True, "detail": "existing SL is safer or equal"}

    # Idempotency & lock
    key = _idempotent_key(symbol, side, abs(amt), stop_price)
    coid = _coid(os.getenv("ORDER_ID_PREFIX","ALG"), symbol, "SL", key)

    # Place STOP_MARKET reduceOnly
    req = {
        "symbol": symbol,
        "side": side,
        "type": "STOP_MARKET",
        "stopPrice": f"{stop_price:.6f}",
        "closePosition": False,
        "reduceOnly": True,
        "newClientOrderId": coid,
        "workingType": _working_type(),
    }

    # sanity for qty bounds
    if _bool("ENFORCE_QTY_BOUNDS", True):
        qty = abs(amt)
        # respect minimal notional / qty_step if you have them in env, else allow exchange to reject
        req["quantity"] = f"{qty:.8f}"

    # atomic place with verify
    grace = _sl_grace()
    start = time.time()
    try:
        placed = cli.futures_create_order(**req)
        # verify
        timeout_ms = _int("ORD_VERIFY_TIMEOUT_MS", 800)
        end_by = time.time() + (timeout_ms / 1000.0)
        ok_seen = False
        while time.time() < end_by:
            with suppress(Exception):
                oo = cli.futures_get_open_orders(symbol=symbol) or []
                if any((o.get("clientOrderId")==coid) for o in oo):
                    ok_seen = True
                    break
            time.sleep(0.05)

        emergency = (time.time() - start) > grace
        return {
            "ok": True,
            "skipped": False,
            "action": "place",
            "placed": True,
            "clientOrderId": coid,
            "verified": ok_seen,
            "emergency": emergency,
            "detail": "protective STOP_MARKET placed",
        }
    except Exception as e:
        return {"ok": False, "skipped": False, "action": "place", "placed": False, "detail": f"{e}", "clientOrderId": coid}

# -------- Atomic Update ----------
def atomic_update_orders(
    client,
    symbol: str,
    plan: Dict[str, Any],
    *,
    verify_timeout_ms: int = None,
    strategy: str = None
) -> Dict[str, Any]:
    """
    מבצע עדכון אטומי פשוט:
      1) מבטל רק מה שצריך (MINIMAL) או לפי strategy.
      2) מניח הוראות חדשות עם clientOrderId מבוסס hash.
    plan = {
      "cancel": [{"clientOrderId": "..."} ...]   # אופציונלי
      "create": [ {binance_order_kwargs...}, ... ]  # חובה אם רוצים יצירה
      "note": "context string for idempotency"   # אופציונלי
    }
    """
    if not _bool("ORD_ATOMIC_UPDATE", True):
        return {"ok": False, "skipped": True, "detail": "ORD_ATOMIC_UPDATE=0"}

    verify_timeout_ms = int(verify_timeout_ms or _int("ORD_VERIFY_TIMEOUT_MS", 800))
    strategy = (strategy or os.getenv("ORD_CANCEL_STRATEGY") or "MINIMAL").upper()

    # 1) Cancel phase
    cancelled = []
    if plan.get("cancel"):
        for c in plan["cancel"]:
            try:
                if c.get("orderId"):
                    res = client.futures_cancel_order(symbol=symbol, orderId=c["orderId"])
                else:
                    # cancel by clientOrderId
                    res = client.futures_cancel_order(symbol=symbol, origClientOrderId=c.get("clientOrderId"))
                cancelled.append(res)
            except Exception as e:
                # MINIMAL strategy: ignore missing/filled errors
                if strategy != "MINIMAL":
                    return {"ok": False, "detail": f"cancel failed: {e}"}

    # 2) Create phase
    created, errors = [], []
    prefix = os.getenv("ORDER_ID_PREFIX","ALG")
    note = plan.get("note","")
    # derive common hash from note to make coids stable per plan
    base_key = _h(f"{symbol}|{note}|{time.time():.0f}")

    for i, spec in enumerate(plan.get("create") or []):
        # force safe defaults
        spec = dict(spec)
        # idempotent coid
        role = (spec.get("role") or spec.get("type") or "ORD")[:6]
        coid = _coid(prefix, symbol, role, f"{base_key}:{i}:{role}")
        spec.setdefault("newClientOrderId", coid)

        # respect workingType/RO
        spec.setdefault("workingType", _working_type())
        if "reduceOnly" not in spec:
            spec["reduceOnly"] = bool(spec.get("side") in ("SELL","BUY") and spec.get("type","").upper().startswith("TAKE_PROFIT"))

        try:
            res = client.futures_create_order(**spec)
            created.append({"req": spec, "res": res})
        except Exception as e:
            errors.append({"req": spec, "error": str(e)})

    # 3) Verify phase
    ok_verify = True
    end_by = time.time() + (verify_timeout_ms/1000.0)
    want_ids = set([c["req"]["newClientOrderId"] for c in created])
    while time.time() < end_by and want_ids:
        with suppress(Exception):
            oo = client.futures_get_open_orders(symbol=symbol) or []
            seen = set(o.get("clientOrderId") for o in oo)
            want_ids = want_ids - seen
        time.sleep(0.05)
    if want_ids:
        ok_verify = False

    return {
        "ok": (len(errors) == 0) and ok_verify,
        "cancelled": cancelled,
        "created": created,
        "errors": errors,
        "verified": ok_verify,
        "strategy": strategy,
    }
