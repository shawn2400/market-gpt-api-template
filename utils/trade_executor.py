# -*- coding: utf-8 -*-
from __future__ import annotations
import os, time, logging, asyncio
from contextlib import suppress
from typing import Optional, Dict, Any, List, Tuple
import httpx
from utils.binance_client import (
    get_price,
    futures_mark_price,
    set_leverage,
    futures_create_order,
    get_all_orders,
    futures_cancel_order,
    get_price_coalesced,
)
from utils.trade_execution_core import (
    ALLOW_MARKET_ENTRY,
    ENTRY_BAND_BPS,
    STOP_BAND_BPS,
    ESCALATE_AFTER_S,
    ESCALATE_SLIP_BPS,
    PERCENT_PRICE_GUARD_BPS,
    SLIPPAGE_GUARD_BPS,
    POST_FILL_SANITY_BPS,
    ENFORCE_POST_FILL_SANITY,
    QUALITY_DEFAULT,
    MIN_QUALITY_SCORE,
    MIN_QUALITY_FALLBACK,
    MAX_ATR_PCT,
    MIN_VOLUME,
    ENFORCE_APPROVAL_ALWAYS,
    REQUIRE_TP_AND_SL,
    LADDER_TP_ENABLE,
    LADDER_TP_KIND,
    LADDER_TP_DEFAULT_PCTS,
    LADDER_TP_DEFAULT_SPLITS,
    LADDER_SL_ENABLE,
    LADDER_SL_DEFAULT_PCTS,
    TRAIL_CALLBACK_MIN_PCT,
    TRAIL_CALLBACK_MAX_PCT,
    BUDGET_DYNAMIC_ENABLE,
    BUDGET_USE_BALANCE,
    BUDGET_DYNAMIC_RISK_PCTS,
    DYN_LEVERAGE_ENABLE,
    MIN_LEVERAGE,
    LEV_HARD_CAP,
    LEV_ADX_MAP_JSON,
    ORDER_ID_PREFIX,
    CANCEL_ONLY_PREFIXED_ORDERS,
    CANCEL_PREFIX_OVERRIDE,
    IDEMPOTENCY_TTL_SEC,
    BOT_TOKEN,
    API_BASE,
    CONFIRM_TTL_SEC,
    TELEGRAM_CHAT_ID,
    TELEGRAM_PARSE_MODE,
    _q_price,
    _q_qty,
    _ensure_min_notional,
    _calc_qty,
    _offset_bps,
    _is_hedge_mode_runtime,
    _effective_position_side,
    _fetch_klines_raw,
    _adx_from_klines,
    _atr_from_klines,
    _quality_gate,
    _choose_budget_dynamic,
    _choose_leverage,
    _parse_csv_floats,
    _cancel_old_closing_orders,
    _normalize_position_side,
    _close_side_for,
    _pos_side_for_entry,
    _normalize_entry_side,
    _compute_tp_sl_targets,
    _compute_trailing_callback_pct,
    _Idem,
)

with suppress(Exception):
    from utils.binance_futures_exec import BinanceFuturesExec
with suppress(Exception):
    from utils.guard_stop import ensure_protective_stop

try:
    from utils.budget import get_budget_usdt
except Exception:
    def get_budget_usdt(
        symbol: Optional[str] = None,
        *,
        quality: Optional[float] = None,
        atr: Optional[float] = None,
        price: Optional[float] = None,
    ) -> float:
        try:
            return float(os.getenv("MAX_TRADE_BUDGET", "100"))
        except Exception:
            return 100.0

try:
    from utils.risk_checker import pre_trade_risk_check, RISK_CHECK_ENABLE
except Exception:
    RISK_CHECK_ENABLE = False

    def pre_trade_risk_check(*args, **kwargs):
        return {"ok": True, "score": 100.0, "reasons": ["risk_module_missing"], "metrics": {}}

try:
    from utils.approvals import ConfirmStore, send_confirm_request, require_approval
except Exception:
    class ConfirmStore:
        pass

    def send_confirm_request(*args, **kwargs):
        return None

    def require_approval(plan: Dict[str, Any]) -> bool:
        return False

log = logging.getLogger("algogpt.trade_executor")

SL_DYNAMIC_ENABLE = os.getenv("SL_DYNAMIC_ENABLE", "1").lower() in ("1", "true", "yes", "on")
SL_ATR_MULT = float(os.getenv("SL_ATR_MULT", "0.6"))
SL_TRAIL_ENABLE = os.getenv("SL_TRAIL_ENABLE", "1").lower() in ("1", "true", "yes", "on")
TRAIL_ENABLE_DEFAULT = os.getenv("TRAIL_ENABLE", "0").lower() in ("1", "true", "yes", "on")
TRAIL_ATR_MULT_DEFAULT = float(os.getenv("TRAIL_ATR_MULT", os.getenv("SL_ATR_MULT", "0.6")))
TRAIL_FREEZE_ENABLE_DEF = os.getenv("TRAIL_FREEZE_ENABLE", "1").lower() in ("1", "true", "yes", "on")
HYBRID_HARD_CANCEL_ENABLE = os.getenv("HYBRID_HARD_CANCEL_ENABLE", "1").lower() in ("1", "true", "yes", "on")
HYBRID_CANCEL_CONFIRM_TRIES = int(os.getenv("HYBRID_CANCEL_CONFIRM_TRIES", "4"))
HYBRID_CANCEL_CONFIRM_SLEEP_MS = int(os.getenv("HYBRID_CANCEL_CONFIRM_SLEEP_MS", "200"))
ARM_VERIFY_DISABLE = os.getenv("ARM_VERIFY_DISABLE", "0").lower() in ("1", "true", "yes", "on")
TP_BE_ONLY_AFTER_TP1 = os.getenv("TP_BE_ONLY_AFTER_TP1", "1").lower() in ("1", "true", "yes", "on")
TP_BE_OFFSET_BPS = float(os.getenv("TP_BE_OFFSET_BPS", "8"))
BE_GUARD_ENABLE = os.getenv("BE_GUARD_ENABLE", "1").lower() in ("1", "true", "yes", "on")
BE_GUARD_EVERY_SEC = int(os.getenv("BE_GUARD_EVERY_SEC", "30"))
TP1_TAGS_ENV = [t.strip() for t in (os.getenv("TP1_TAGS", "") or "").split(",") if t.strip()]


async def _tg_send(text: str) -> Dict[str, Any]:
    chat_id = int(os.getenv("TRADE_LOG_CHAT_ID") or TELEGRAM_CHAT_ID or 0)
    token = os.getenv("TELEGRAM_BOT_TOKEN") or BOT_TOKEN
    if not (chat_id and token):
        return {"ok": False, "skipped": True, "reason": "no_chat_or_token"}
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": TELEGRAM_PARSE_MODE or "HTML",
        "disable_web_page_preview": True,
    }
    try:
        async with httpx.AsyncClient(timeout=12.0) as cli:
            r = await cli.post(f"https://api.telegram.org/bot{token}/sendMessage", json=payload)
        return r.json()
    except Exception as e:
        log.warning("telegram_send_failed: %s", e)
        return {"ok": False, "error": str(e)}


def _coid(kind: str, sym: str, side: str) -> str:
    prefix = (ORDER_ID_PREFIX or "ALG").strip()
    ts = int(time.time() * 1000)
    return f"{prefix}_{kind}_{sym}_{side}_{ts}"


def _ensure_runtime_position_mode() -> None:
    mode = (os.getenv("POSITION_MODE_OVERRIDE", "") or "").strip().lower()
    if not mode:
        return
    try:
        if "BinanceFuturesExec" in globals():
            execu = BinanceFuturesExec()
            if mode in ("hedge", "dual", "dual_side", "dual_side_position", "dualposition"):
                execu.set_position_side_dual(True)
            elif mode in ("oneway", "one_way", "single", "single_side", "oneside"):
                execu.set_position_side_dual(False)
    except Exception as e:
        log.warning("align_position_mode_failed: %s", e)


def _order_matches(
    o: Dict[str, Any],
    *,
    typ: str,
    qty: str,
    stop: Optional[str],
    price: Optional[str],
    side: str,
    eff_ps: str,
    expect_ro: bool,
) -> bool:
    try:
        if str(o.get("type", "")).upper() != typ:
            return False
        if str(o.get("side", "")).upper() != side:
            return False
        if eff_ps != "BOTH" and str(o.get("positionSide", "")).upper() != eff_ps:
            return False
        if eff_ps == "BOTH" and ("positionSide" in o):
            return False
        if expect_ro:
            ro = o.get("reduceOnly")
            if ro not in (True, "true", 1):
                return False
        if qty and str(o.get("origQty") or o.get("quantity") or "") != qty:
            try:
                if abs(float(o.get("origQty", "0")) - float(qty)) > 1e-12:
                    return False
            except Exception:
                return False
        if stop is not None:
            if str(o.get("stopPrice") or "") != stop:
                try:
                    if abs(float(o.get("stopPrice", "0")) - float(stop)) > 1e-9:
                        return False
                except Exception:
                    return False
        if price is not None and typ not in ("STOP_MARKET", "TAKE_PROFIT_MARKET"):
            if str(o.get("price") or "") != price:
                try:
                    if abs(float(o.get("price", "0")) - float(price)) > 1e-9:
                        return False
                except Exception:
                    return False
        st = (o.get("status") or "").upper()
        return st in ("NEW", "PARTIALLY_FILLED")
    except Exception:
        return False


def _place_close_order_hardened(
    args: Dict[str, Any],
    *,
    sym: str,
    typ: str,
    qty_str: str,
    stop_str: Optional[str],
    price_str: Optional[str],
    side: str,
    eff_ps: str,
    expect_ro: bool,
    place_fn,
    list_fn,
    cancel_fn,
    max_retries: int = 3,
) -> Dict[str, Any]:
    if ARM_VERIFY_DISABLE:
        try:
            return {"ok": True, "response": place_fn(**args)}
        except Exception as e:
            msg = str(e).lower()
            if ("reduceonly" in msg or "-1106" in msg or "reduce only" in msg) and "reduceOnly" in args:
                a2 = dict(args)
                a2.pop("reduceOnly", None)
                return {"ok": True, "response": place_fn(**a2)}
            raise
    backoff = 0.35
    last_err: Optional[str] = None
    for attempt in range(1, max_retries + 1):
        try:
            resp = place_fn(**args)
        except Exception as e:
            msg = str(e).lower()
            if ("reduceonly" in msg or "-1106" in msg or "reduce only" in msg) and "reduceOnly" in args:
                a2 = dict(args)
                a2.pop("reduceOnly", None)
                try:
                    resp = place_fn(**a2)
                except Exception as e2:
                    last_err = f"place_failed(ro_fallback): {e2}"
                    time.sleep(backoff)
                    backoff = min(1.5, backoff * 1.6)
                    continue
            else:
                last_err = f"place_failed: {e}"
                time.sleep(backoff)
                backoff = min(1.5, backoff * 1.6)
                continue
        oid = str(resp.get("orderId") or "")
        ok = False
        try:
            lst = list_fn(sym, limit=50) or []
            cand = next((o for o in lst if str(o.get("orderId")) == oid), None)
            if cand and _order_matches(
                cand,
                typ=typ,
                qty=qty_str,
                stop=stop_str,
                price=price_str,
                side=side,
                eff_ps=eff_ps,
                expect_ro=expect_ro,
            ):
                ok = True
        except Exception as e:
            last_err = f"verify_failed: {e}"
        if ok:
            return {"ok": True, "response": resp}
        with suppress(Exception):
            cancel_fn(sym, oid)
        time.sleep(backoff)
        backoff = min(1.5, backoff * 1.6)
    return {"ok": False, "error": last_err or "verify_mismatch_after_place"}


def _side_norm(side: str) -> str:
    s = (side or "").upper()
    return "BUY" if s in ("BUY", "LONG") else "SELL"


def _maybe_price(sym: str, prefer_mark: bool = True) -> Optional[float]:
    v = None
    if prefer_mark:
        v = futures_mark_price(sym)
    if v is None:
        v = get_price_coalesced(sym) or get_price(sym) or futures_mark_price(sym)
    return v


def _ensure_qty(
    sym: str,
    qty: Optional[float],
    *,
    budget_usdt: Optional[float],
    price: Optional[float],
    leverage: Optional[float],
) -> Tuple[str, float]:
    if qty is None or qty <= 0:
        if not (budget_usdt and price and leverage and leverage > 0):
            raise ValueError("qty_missing_and_no_budget")
        raw = (float(budget_usdt) * float(leverage)) / float(price)
        qf = max(0.0, raw)
    else:
        qf = float(qty)
    q_str = _q_qty(sym, qf)
    q_str = _ensure_min_notional(sym, float(price or 0.0), q_str)
    try:
        qf2 = float(q_str)
    except Exception:
        qf2 = qf
    if qf2 <= 0:
        raise ValueError("qty_non_positive_after_quantize")
    return q_str, qf2


def _approve_if_needed(idem: _Idem, plan: Dict[str, Any]) -> None:
    if not require_approval(plan):
        return
    ttl = int(plan.get("confirm_ttl_sec") or CONFIRM_TTL_SEC or 600)
    send_confirm_request(idem, plan, ttl=ttl)


def _tp_side(side_entry: str) -> str:
    return "SELL" if side_entry.upper() == "BUY" else "BUY"


def _place_tp_sl_for_position(
    symbol: str,
    side_entry: str,
    qty_str: str,
    entry_price: Optional[float],
    tp_targets: List[Dict[str, Any]],
    sl_target: Optional[Dict[str, Any]],
    *,
    eff_position_side: str,
    client_tag: str,
) -> Dict[str, Any]:
    results: Dict[str, Any] = {"tp": [], "sl": None}
    close_side = _tp_side(side_entry)
    for i, leg in enumerate(tp_targets, start=1):
        px = float(leg["price"])
        part_qty_str = _q_qty(symbol, float(leg["qty"]))
        args = {
            "symbol": symbol.upper(),
            "side": close_side,
            "type": "TAKE_PROFIT",
            "reduceOnly": True,
            "quantity": part_qty_str,
            "price": _q_price(symbol, px),
            "stopPrice": _q_price(symbol, px),
            "timeInForce": "GTC",
            "newClientOrderId": _coid(f"TP{i}", symbol, close_side) if ORDER_ID_PREFIX else None,
        }
        if eff_position_side != "BOTH":
            args["positionSide"] = eff_position_side
        res = _place_close_order_hardened(
            args,
            sym=symbol,
            typ="TAKE_PROFIT",
            qty_str=part_qty_str,
            stop_str=args["stopPrice"],
            price_str=args["price"],
            side=close_side,
            eff_ps=eff_position_side,
            expect_ro=True,
            place_fn=futures_create_order,
            list_fn=get_all_orders,
            cancel_fn=futures_cancel_order,
        )
        results["tp"].append(res)
    if sl_target and float(sl_target.get("price") or 0.0) > 0:
        sl_px = float(sl_target["price"])
        sl_args = {
            "symbol": symbol.upper(),
            "side": close_side,
            "type": "STOP",
            "reduceOnly": True,
            "quantity": qty_str,
            "price": _q_price(symbol, sl_px),
            "stopPrice": _q_price(symbol, sl_px),
            "timeInForce": "GTC",
            "newClientOrderId": _coid("SL", symbol, close_side) if ORDER_ID_PREFIX else None,
        }
        if eff_position_side != "BOTH":
            sl_args["positionSide"] = eff_position_side
        sl_res = _place_close_order_hardened(
            sl_args,
            sym=symbol,
            typ="STOP",
            qty_str=qty_str,
            stop_str=sl_args["stopPrice"],
            price_str=sl_args["price"],
            side=close_side,
            eff_ps=eff_position_side,
            expect_ro=True,
            place_fn=futures_create_order,
            list_fn=get_all_orders,
            cancel_fn=futures_cancel_order,
        )
        results["sl"] = sl_res
    return results


def _place_hybrid_entry(
    symbol: str,
    side: str,
    qty_str: str,
    *,
    entry_ref_px: float,
    band_bps: float,
    escalate_after_s: int,
    escalate_slip_bps: float,
    eff_position_side: str,
    client_tag: str,
) -> Dict[str, Any]:
    side_u = side.upper()
    limit_px = _offset_bps(entry_ref_px, -band_bps if side_u == "BUY" else band_bps)
    limit_args = {
        "symbol": symbol.upper(),
        "side": side_u,
        "type": "LIMIT",
        "quantity": qty_str,
        "price": _q_price(symbol, float(limit_px)),
        "timeInForce": "GTC",
        "newClientOrderId": _coid("HYB_LMT", symbol, side_u) if ORDER_ID_PREFIX else None,
    }
    if eff_position_side != "BOTH":
        limit_args["positionSide"] = eff_position_side
    place_res = futures_create_order(**limit_args)
    oid = place_res.get("orderId")
    out: Dict[str, Any] = {"entry_limit": place_res}
    t0 = time.time()
    while True:
        if (time.time() - t0) >= int(escalate_after_s):
            break
        time.sleep(0.4)
    if oid is not None and HYBRID_HARD_CANCEL_ENABLE:
        try:
            futures_cancel_order(symbol.upper(), oid)
            for _ in range(HYBRID_CANCEL_CONFIRM_TRIES):
                time.sleep(HYBRID_CANCEL_CONFIRM_SLEEP_MS / 1000.0)
                oo = get_all_orders(symbol.upper(), limit=20) or []
                still = next(
                    (o for o in oo if str(o.get("orderId")) == str(oid) and (o.get("status", "")).upper() == "NEW"),
                    None,
                )
                if not still:
                    break
        except Exception as e:
            log.warning("hybrid_cancel_limit_failed: %s", e)
    ref_px = float(_maybe_price(symbol) or entry_ref_px)
    _ = _offset_bps(ref_px, ESCALATE_SLIP_BPS if side_u == "BUY" else -ESCALATE_SLIP_BPS)
    mkt_args = {
        "symbol": symbol.upper(),
        "side": side_u,
        "type": "MARKET",
        "quantity": qty_str,
        "newClientOrderId": _coid("HYB_MKT", symbol, side_u) if ORDER_ID_PREFIX else None,
    }
    if eff_position_side != "BOTH":
        mkt_args["positionSide"] = eff_position_side
    out["entry_market"] = futures_create_order(**mkt_args)
    return out


def _place_direct_entry(
    symbol: str,
    side: str,
    qty_str: str,
    entry_price: Optional[float],
    *,
    order_type: str,
    eff_position_side: str,
    client_tag: str,
) -> Dict[str, Any]:
    side_u = side.upper()
    typ = order_type.upper()
    if typ == "MARKET":
        args = {
            "symbol": symbol.upper(),
            "side": side_u,
            "type": "MARKET",
            "quantity": qty_str,
            "newClientOrderId": _coid("MKT", symbol, side_u) if ORDER_ID_PREFIX else None,
        }
        if eff_position_side != "BOTH":
            args["positionSide"] = eff_position_side
        res = futures_create_order(**args)
        return {"entry_market": res}
    elif typ == "LIMIT":
        if entry_price is None or float(entry_price) <= 0:
            raise ValueError("limit_price_missing")
        args = {
            "symbol": symbol.upper(),
            "side": side_u,
            "type": "LIMIT",
            "timeInForce": "GTC",
            "quantity": qty_str,
            "price": _q_price(symbol, float(entry_price)),
            "newClientOrderId": _coid("LMT", symbol, side_u) if ORDER_ID_PREFIX else None,
        }
        if eff_position_side != "BOTH":
            args["positionSide"] = eff_position_side
        res = futures_create_order(**args)
        return {"entry_limit": res}
    else:
        raise ValueError(f"unsupported_order_type:{order_type}")


def _compute_dynamic_sl_price(side: str, ref_price: float, atr_val: Optional[float], *, atr_mult: float) -> Optional[float]:
    if not (atr_val and atr_val > 0.0):
        return None
    if side.upper() == "BUY":
        return max(1e-12, ref_price - atr_mult * atr_val)
    return max(1e-12, ref_price + atr_mult * atr_val)


def _maybe_breakeven_after_tp1(
    plan: Dict[str, Any],
    symbol: str,
    side: str,
    entry_price: float,
    eff_position_side: str,
    qty_str: str,
) -> Optional[Dict[str, Any]]:
    if not BE_GUARD_ENABLE:
        return None
    tags = [t.strip().lower() for t in (plan.get("tags") or [])] + [t.lower() for t in TP1_TAGS_ENV]
    if TP_BE_ONLY_AFTER_TP1 and "tp1" not in tags:
        return None
    be_px = _offset_bps(entry_price, TP_BE_OFFSET_BPS if side.upper() == "BUY" else -TP_BE_OFFSET_BPS)
    try:
        _cancel_old_closing_orders(symbol, eff_position_side, kinds=("STOP", "STOP_MARKET"))
    except Exception:
        pass
    close_side = _tp_side(side)
    args = {
        "symbol": symbol.upper(),
        "side": close_side,
        "type": "STOP",
        "reduceOnly": True,
        "quantity": qty_str,
        "price": _q_price(symbol, float(be_px)),
        "stopPrice": _q_price(symbol, float(be_px)),
        "timeInForce": "GTC",
        "newClientOrderId": _coid("SL_BE", symbol, close_side) if ORDER_ID_PREFIX else None,
    }
    if eff_position_side != "BOTH":
        args["positionSide"] = eff_position_side
    res = _place_close_order_hardened(
        args,
        sym=symbol,
        typ="STOP",
        qty_str=qty_str,
        stop_str=args["stopPrice"],
        price_str=args["price"],
        side=close_side,
        eff_ps=eff_position_side,
        expect_ro=True,
        place_fn=futures_create_order,
        list_fn=get_all_orders,
        cancel_fn=futures_cancel_order,
    )
    return res


def execute_trade_live(plan: Dict[str, Any]) -> Dict[str, Any]:
    t0 = time.time()
    symbol = str(plan.get("symbol") or "").upper().strip()
    if not symbol:
        return {"ok": False, "error": "symbol_missing"}
    side_in = _normalize_entry_side(plan.get("side"))
    if side_in not in ("BUY", "SELL"):
        return {"ok": False, "error": "invalid_side"}
    _ensure_runtime_position_mode()
    try:
        kl = _fetch_klines_raw(symbol, "15m", limit=120)
    except Exception:
        kl = None
    with suppress(Exception):
        adx = _adx_from_klines(kl) if kl else 0.0
    with suppress(Exception):
        atr = _atr_from_klines(kl) if kl else 0.0
    adx = float(locals().get("adx", 0.0))
    atr = float(locals().get("atr", 0.0))
    quality = float(plan.get("score") or plan.get("quality") or QUALITY_DEFAULT)
    ok, reason_bad = _quality_gate(
        quality=quality,
        min_score=MIN_QUALITY_SCORE or MIN_QUALITY_FALLBACK,
        atr_pct=plan.get("atr_pct"),
        atr_abs=atr,
        max_atr_pct=MAX_ATR_PCT,
        volume=plan.get("vol"),
        min_volume=MIN_VOLUME,
    )
    if not ok:
        return {"ok": False, "error": "quality_gate_failed", "detail": reason_bad}
    idem = _Idem(prefix="trade", ttl=IDEMPOTENCY_TTL_SEC)
    _approve_if_needed(idem, plan)
    leverage = _choose_leverage(
        symbol,
        float(adx),
        int(plan.get("leverage") or plan.get("lev") or MIN_LEVERAGE),
    )
    if leverage is None or leverage < (MIN_LEVERAGE or 1):
        leverage = max(1, MIN_LEVERAGE or 1)
    leverage = min(int(leverage), int(LEV_HARD_CAP or leverage))
    try:
        set_leverage(symbol, int(leverage))
    except Exception as e:
        log.warning("set_leverage_failed %s lev=%s: %s", symbol, leverage, e)
    entry_ref_px = float(plan.get("entry_price") or plan.get("price") or (get_price_coalesced(symbol) or 0.0))
    if not entry_ref_px:
        p = _maybe_price(symbol)
        entry_ref_px = float(p or 0.0)
    if entry_ref_px <= 0:
        return {"ok": False, "error": "no_price_available"}
    dyn_budget = _choose_budget_dynamic(get_budget_usdt, quality=quality, price=entry_ref_px, symbol=symbol)
    if dyn_budget is None:
        dyn_budget = get_budget_usdt(symbol, quality=quality, atr=atr, price=entry_ref_px)
    qty_str, qty_f = _ensure_qty(
        symbol,
        qty=plan.get("qty"),
        budget_usdt=dyn_budget,
        price=entry_ref_px,
        leverage=leverage,
    )
    eff_ps = _effective_position_side(
        plan.get("position_side") or _pos_side_for_entry(side_in),
        hedge_runtime=_is_hedge_mode_runtime(),
    )
    order_type = str(plan.get("order_type") or plan.get("entry_type") or "MARKET").upper()
    if order_type == "HYBRID":
        entry_res = _place_hybrid_entry(
            symbol,
            side_in,
            qty_str,
            entry_ref_px=entry_ref_px,
            band_bps=float(ENTRY_BAND_BPS or 0.0),
            escalate_after_s=int(ESCALATE_AFTER_S or 6),
            escalate_slip_bps=float(ESCALATE_SLIP_BPS or 0.0),
            eff_position_side=eff_ps,
            client_tag="HYB",
        )
    else:
        entry_res = _place_direct_entry(
            symbol,
            side_in,
            qty_str,
            entry_price=float(plan.get("limit_price") or plan.get("entry_price") or entry_ref_px)
            if order_type == "LIMIT"
            else None,
            order_type=order_type,
            eff_position_side=eff_ps,
            client_tag="DIR",
        )
    targets = _compute_tp_sl_targets(
        symbol=symbol,
        side=side_in,
        qty=qty_f,
        price_ref=entry_ref_px,
        plan=plan,
        ladder_tp_enable=LADDER_TP_ENABLE,
        ladder_tp_kind=LADDER_TP_KIND,
        ladder_tp_default_pcts=LADDER_TP_DEFAULT_PCTS,
        ladder_tp_default_splits=LADDER_TP_DEFAULT_SPLITS,
        ladder_sl_enable=LADDER_SL_ENABLE,
        ladder_sl_default_pcts=LADDER_SL_DEFAULT_PCTS,
        sl_dynamic_enable=SL_DYNAMIC_ENABLE,
        sl_atr_mult=SL_ATR_MULT,
        atr_abs=atr,
        stop_band_bps=STOP_BAND_BPS,
    )
    if SL_DYNAMIC_ENABLE and atr and not targets.get("sl"):
        dyn_sl = _compute_dynamic_sl_price(side_in, entry_ref_px, atr, atr_mult=SL_ATR_MULT)
        if dyn_sl:
            targets["sl"] = {"price": dyn_sl, "qty": qty_f}
    tpsl_res = _place_tp_sl_for_position(
        symbol=symbol,
        side_entry=side_in,
        qty_str=qty_str,
        entry_price=entry_ref_px,
        tp_targets=targets.get("tp") or [],
        sl_target=targets.get("sl"),
        eff_position_side=eff_ps,
        client_tag="CLS",
    )
    be_res = None
    with suppress(Exception):
        be_res = _maybe_breakeven_after_tp1(
            plan=plan,
            symbol=symbol,
            side=side_in,
            entry_price=entry_ref_px,
            eff_position_side=eff_ps,
            qty_str=qty_str,
        )
    trail_enable = bool(plan.get("trail_enable", TRAIL_ENABLE_DEFAULT))
    trail_cb_pct = None
    if trail_enable:
        try:
            trail_cb_pct = _compute_trailing_callback_pct(
                plan=plan,
                atr_abs=atr,
                min_pct=TRAIL_CALLBACK_MIN_PCT,
                max_pct=TRAIL_CALLBACK_MAX_PCT,
                default_mult=TRAIL_ATR_MULT_DEFAULT,
            )
        except Exception as e:
            log.warning("trail_compute_failed: %s", e)
    with suppress(Exception):
        if "ensure_protective_stop" in globals():
            ensure_protective_stop(symbol, side_in, qty_str, eff_ps, entry_ref_px, targets.get("sl"))
    elapsed = time.time() - t0
    return {
        "ok": True,
        "symbol": symbol,
        "side": side_in,
        "leverage": leverage,
        "qty": qty_str,
        "entry": entry_res,
        "tpsl": tpsl_res,
        "be": be_res,
        "trail": {
            "enabled": trail_enable,
            "callback_pct": trail_cb_pct,
            "note": "requires external worker for dynamic updates" if trail_enable else None,
        },
        "elapsed_sec": round(elapsed, 3),
    }


def _safe_close_position(symbol: str, side_opened: str, qty: float, *, eff_position_side: str) -> Dict[str, Any]:
    close_side = _tp_side(side_opened)
    qty_str = _q_qty(symbol, float(qty))
    args = {
        "symbol": symbol.upper(),
        "side": close_side,
        "type": "MARKET",
        "reduceOnly": True,
        "quantity": qty_str,
        "newClientOrderId": _coid("CLOSE", symbol, close_side) if ORDER_ID_PREFIX else None,
    }
    if eff_position_side != "BOTH":
        args["positionSide"] = eff_position_side
    try:
        res = futures_create_order(**args)
        return {"ok": True, "response": res}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def execute_trade_live_async(plan: Dict[str, Any]) -> Dict[str, Any]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, execute_trade_live, plan)


__all__ = ["execute_trade_live", "execute_trade_live_async", "_safe_close_position"]









































































































