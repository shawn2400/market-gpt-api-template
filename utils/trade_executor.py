# utils/trade_executor.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import os, time, logging, asyncio
from contextlib import suppress
from typing import Optional, Dict, Any, List

import httpx  # ← להודעות טלגרם ישירות מהמודול

from utils.binance_client import (
    get_price, futures_mark_price, set_leverage, futures_create_order,
    get_all_orders, futures_cancel_order,
)

# ====== Optional dynamic budget hook ======
try:
    from utils.budget import get_budget_usdt
except Exception:
    def get_budget_usdt(symbol: Optional[str] = None, *, quality: Optional[float] = None,
                        atr: Optional[float] = None, price: Optional[float] = None) -> float:  # type: ignore
        try:
            return float(os.getenv("MAX_TRADE_BUDGET", "100"))
        except Exception:
            return 100.0

# ====== Optional risk hook ======
try:
    from utils.risk_checker import pre_trade_risk_check, RISK_CHECK_ENABLE
except Exception:
    RISK_CHECK_ENABLE = False
    def pre_trade_risk_check(*args, **kwargs):  # type: ignore
        return {"ok": True, "score": 100.0, "reasons": ["risk_module_missing"], "metrics": {}}

# ====== Core helpers & constants ======
from utils.trade_execution_core import (
    # env & constants
    ALLOW_MARKET_ENTRY, ENTRY_BAND_BPS, STOP_BAND_BPS, ESCALATE_AFTER_S, ESCALATE_SLIP_BPS,
    PERCENT_PRICE_GUARD_BPS, SLIPPAGE_GUARD_BPS, POST_FILL_SANITY_BPS, ENFORCE_POST_FILL_SANITY,
    QUALITY_DEFAULT, MIN_QUALITY_SCORE, MIN_QUALITY_FALLBACK, MAX_ATR_PCT, MIN_VOLUME,
    ENFORCE_APPROVAL_ALWAYS, REQUIRE_TP_AND_SL,
    LADDER_TP_ENABLE, LADDER_TP_KIND, LADDER_TP_DEFAULT_PCTS, LADDER_TP_DEFAULT_SPLITS,
    LADDER_SL_ENABLE, LADDER_SL_DEFAULT_PCTS,
    TRAIL_CALLBACK_MIN_PCT, TRAIL_CALLBACK_MAX_PCT,
    BUDGET_DYNAMIC_ENABLE, BUDGET_USE_BALANCE, BUDGET_DYNAMIC_RISK_PCTS,
    DYN_LEVERAGE_ENABLE, MIN_LEVERAGE, LEV_HARD_CAP, LEV_ADX_MAP_JSON,
    ORDER_ID_PREFIX, CANCEL_ONLY_PREFIXED_ORDERS, CANCEL_PREFIX_OVERRIDE,
    IDEMPOTENCY_TTL_SEC, BOT_TOKEN, API_BASE, CONFIRM_TTL_SEC, TELEGRAM_CHAT_ID, TELEGRAM_PARSE_MODE,
    # helpers
    _q_price, _q_qty, _ensure_min_notional, _calc_qty, _offset_bps,
    _is_hedge_mode_runtime, _effective_position_side,
    _fetch_klines_raw, _adx_from_klines, _atr_from_klines, _quality_gate,
    _choose_budget_dynamic, _choose_leverage, _parse_csv_floats,
    _cancel_old_closing_orders, _build_ladders, _normalize_position_side,
    _close_side_for, _pos_side_for_entry, _normalize_entry_side,
    _compute_tp_sl_targets, _compute_trailing_callback_pct,
    _Idem,
)

# ← מוסיף את ממשק האישור (סטאבים ב-approvals אם אין מודול מלא)
from utils.approvals import ConfirmStore, send_confirm_request, require_approval  # type: ignore

# ← אופציונלי: ביצוע ישיר ל-Futures בשביל יישור מצב חשבון (Hedge/One-way)
with suppress(Exception):
    from utils.binance_futures_exec import BinanceFuturesExec  # type: ignore

log = logging.getLogger("algogpt.trade_executor")

# ─────────── Feature flags for trail (ENV override-able per ticket) ───────────
SL_DYNAMIC_ENABLE     = os.getenv("SL_DYNAMIC_ENABLE", "1").lower() in ("1","true","yes","on")
SL_ATR_MULT           = float(os.getenv("SL_ATR_MULT", "0.6"))
SL_TRAIL_ENABLE       = os.getenv("SL_TRAIL_ENABLE", "1").lower() in ("1","true","yes","on")

TRAIL_ENABLE_DEFAULT    = os.getenv("TRAIL_ENABLE", "0").lower() in ("1","true","yes","on")
TRAIL_ATR_MULT_DEFAULT  = float(os.getenv("TRAIL_ATR_MULT", os.getenv("SL_ATR_MULT", "0.6")))
TRAIL_FREEZE_ENABLE_DEF = os.getenv("TRAIL_FREEZE_ENABLE", "1").lower() in ("1","true","yes","on")

# ─────────── Telegram helper ───────────
async def _tg_send(text: str) -> Dict[str, Any]:
    chat_id = int(os.getenv("TRADE_LOG_CHAT_ID") or TELEGRAM_CHAT_ID or 0)
    token = os.getenv("TELEGRAM_BOT_TOKEN") or BOT_TOKEN
    if not (chat_id and token):
        return {"ok": False, "skipped": True}
    payload = {"chat_id": chat_id, "text": text, "parse_mode": TELEGRAM_PARSE_MODE or "HTML", "disable_web_page_preview": True}
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

# ─────────── Align position mode helper (fix -4061) ───────────
def _ensure_runtime_position_mode() -> None:
    """
    מיישר את מצב החשבון (Hedge/One-Way) מול Binance לפי POSITION_MODE_OVERRIDE אם הוגדר.
    רץ באופן שקט; כישלון לא מפיל את הזרימה.
    """
    mode = (os.getenv("POSITION_MODE_OVERRIDE", "") or "").strip().lower()
    if not mode:
        return
    try:
        if 'BinanceFuturesExec' in globals():
            execu = BinanceFuturesExec()
            if mode in ("hedge","dual","dual_side","dual_side_position","dualposition"):
                execu.set_position_side_dual(True)   # Hedge
            elif mode in ("oneway","one_way","single","single_side","oneside"):
                execu.set_position_side_dual(False)  # One-way
    except Exception as e:
        log.warning("align_position_mode_failed: %s", e)

# ─────────── Hybrid entry (LIMIT+STOP עם positionSide מותנה) ───────────
async def _place_hybrid_entry(sym: str, side: str, qty: float, base_price: float,
                              ref_entry: Optional[float], position_side: str) -> Dict[str, Any]:
    ref = ref_entry if ref_entry is not None else base_price
    if side == "BUY":
        limit_price = _offset_bps(ref, -ENTRY_BAND_BPS, +1)
        stop_price  = _offset_bps(ref, +STOP_BAND_BPS,  +1)
    else:
        limit_price = _offset_bps(ref, +ENTRY_BAND_BPS, +1)
        stop_price  = _offset_bps(ref, -STOP_BAND_BPS,  +1)

    cur = get_price(sym) or futures_mark_price(sym) or base_price
    slip_bps_now = abs(cur - ref) / max(ref, 1e-9) * 10000.0
    if slip_bps_now >= SLIPPAGE_GUARD_BPS:
        return {"ok": False, "reason": "slippage_guard", "slip_bps": slip_bps_now}

    limit_str, limit_p = _q_price(sym, float(limit_price))
    stop_str , stop_p  = _q_price(sym, float(stop_price))
    qty_str  , _       = _q_qty(sym, qty)

    eff_ps = _effective_position_side(position_side)

    entry_kwargs = dict(
        symbol=sym, side=side, type="LIMIT",
        timeInForce="GTC", price=limit_str, quantity=qty_str,
        reduceOnly=False, newClientOrderId=_coid("ENTRY_LIM", sym, side),
    )
    if eff_ps != "BOTH":
        entry_kwargs["positionSide"] = eff_ps
    lim = futures_create_order(**entry_kwargs)
    lim_id = str(lim.get("orderId") or "")

    stop_kwargs = dict(
        symbol=sym, side=side, type="STOP",
        timeInForce="GTC", stopPrice=stop_str, price=stop_str, quantity=qty_str,
        reduceOnly=False, workingType="MARK_PRICE",
        newClientOrderId=_coid("ENTRY_STP", sym, side),
    )
    if eff_ps != "BOTH":
        stop_kwargs["positionSide"] = eff_ps
    stp = futures_create_order(**stop_kwargs)
    stp_id = str(stp.get("orderId") or "")

    def _is_filled(oid: str):
        try:
            lst = get_all_orders(sym, limit=20) or []
            for o in lst:
                if str(o.get("orderId")) == str(oid):
                    st = (o.get("status") or "").upper()
                    if st in ("FILLED", "PARTIALLY_FILLED"):
                        ap = o.get("avgPrice") or o.get("price")
                        try:
                            return True, float(ap) if ap is not None else None
                        except Exception:
                            return True, None
        except Exception:
            pass
        return False, None

    t0 = time.time()
    while True:
        lim_filled, lim_fill_px = await asyncio.to_thread(_is_filled, lim_id)
        stp_filled, stp_fill_px = await asyncio.to_thread(_is_filled, stp_id)

        if lim_filled and not stp_filled:
            with suppress(Exception): futures_cancel_order(sym, lim_id)
            mk = get_price(sym) or futures_mark_price(sym) or lim_fill_px or limit_p
            if mk and lim_fill_px:
                bps = abs(lim_fill_px - mk) / max(mk, 1e-9) * 10000.0
                return {"ok": True, "entry_kind": "LIMIT", "price": lim_fill_px, "sanity_bps": bps, "sanity_ok": bps <= POST_FILL_SANITY_BPS, "order": lim}
            return {"ok": True, "entry_kind": "LIMIT", "price": lim_fill_px or limit_p, "sanity_bps": None, "sanity_ok": True, "order": lim}

        if stp_filled and not lim_filled:
            with suppress(Exception): futures_cancel_order(sym, lim_id)
            mk = get_price(sym) or futures_mark_price(sym) or stp_fill_px or stop_p
            if mk and stp_fill_px:
                bps = abs(stp_fill_px - mk) / max(mk, 1e-9) * 10000.0
                return {"ok": True, "entry_kind": "STOP", "price": stp_fill_px, "sanity_bps": bps, "sanity_ok": bps <= POST_FILL_SANITY_BPS, "order": stp}
            return {"ok": True, "entry_kind": "STOP", "price": stp_fill_px or stop_p, "sanity_bps": None, "sanity_ok": True, "order": stp}

        if time.time() - t0 >= ESCALATE_AFTER_S:
            cur = get_price(sym) or futures_mark_price(sym) or base_price
            slip_bps = abs(cur - limit_p) / max(limit_p, 1e-9) * 10000.0
            gate = _quality_gate(sym, side)
            justified = (gate.get("enter_ok") is True) and (slip_bps >= ESCALATE_SLIP_BPS)
            if ALLOW_MARKET_ENTRY and justified:
                with suppress(Exception):
                    if lim_id: futures_cancel_order(sym, lim_id)
                with suppress(Exception):
                    if stp_id: futures_cancel_order(sym, stp_id)
                mkt_kwargs = dict(
                    symbol=sym, side=side, type="MARKET", quantity=qty_str, reduceOnly=False,
                    newClientOrderId=_coid("ENTRY_MKT", sym, side),
                )
                if eff_ps != "BOTH":
                    mkt_kwargs["positionSide"] = eff_ps
                mkt = futures_create_order(**mkt_kwargs)
                mk = get_price(sym) or futures_mark_price(sym) or cur
                bps = abs((cur or 0) - (mk or 0)) / max(mk or 1e-9, 1e-9) * 10000.0 if mk and cur else None
                return {"ok": True, "entry_kind": "MARKET_ESCALATE", "price": float(cur), "sanity_bps": bps, "sanity_ok": (bps is None) or (bps <= POST_FILL_SANITY_BPS), "order": mkt}
            t0 = time.time()
        await asyncio.sleep(1.0)

# ─────────── Public API ───────────
async def execute_trade_live(
    symbol: str, side: str, *,
    budget: Optional[float] = None, leverage: int = 5, dry_run: bool = True,
    quantity: Optional[float] = None, entry: Optional[float] = None,
    sl: Optional[float] = None, tp: Optional[float] = None,
    tp_targets: Optional[List[float]] = None, tp_splits: Optional[List[float]] = None,
    sl_targets: Optional[List[float]] = None, sl_splits: Optional[List[float]] = None,
    confirm_first: bool = True, telegram_chat_id: Optional[int] = None,
    position_side: str = "BOTH", reduce_only: bool = False,
    # Trail controls
    trail: Optional[bool] = None,
    trail_atr_mult: Optional[float] = None,
    trail_freeze: Optional[bool] = None,
) -> Dict[str, Any]:

    side = _normalize_entry_side(side)
    sym = symbol.upper().strip()
    position_side = _effective_position_side(_normalize_position_side(position_side))

    base_price = get_price(sym) or futures_mark_price(sym)
    if not base_price or base_price <= 0:
        raise RuntimeError(f"Cannot fetch price for {sym}")

    # Resolve trail flags (ticket > ENV)
    trail_enabled = bool(TRAIL_ENABLE_DEFAULT if trail is None else trail)
    trail_mult    = float(TRAIL_ATR_MULT_DEFAULT if (trail_atr_mult is None) else trail_atr_mult)
    trail_freeze_enabled = bool(TRAIL_FREEZE_ENABLE_DEF if (trail_freeze is None) else trail_freeze)

    ref_for_guard = float(entry or base_price)
    mk = float(get_price(sym) or futures_mark_price(sym) or base_price)
    pp_bps = abs(mk - ref_for_guard) / max(ref_for_guard, 1e-9) * 10000.0
    if pp_bps >= PERCENT_PRICE_GUARD_BPS:
        return {"ok": False, "reason": "percent_price_guard", "bps": pp_bps, "mk": mk, "ref": ref_for_guard}

    gate = _quality_gate(sym, side)
    try:
        score_for_budget: Optional[float] = float(gate.get("score")) if gate.get("score") is not None else QUALITY_DEFAULT
    except Exception:
        score_for_budget = QUALITY_DEFAULT

    try:
        kl = _fetch_klines_raw(sym, "1m", 60)
        atr_for_budget: Optional[float] = _atr_from_klines(kl, 14) if kl else None
        adx_for_lev: float = _adx_from_klines(kl, 14) if kl else 0.0
    except Exception:
        atr_for_budget = None
        adx_for_lev = 0.0
        kl = None

    dyn_leverage = _choose_leverage(sym, adx_for_lev, leverage)

    if BUDGET_DYNAMIC_ENABLE and (budget is None or float(budget) <= 0):
        budget = _choose_budget_dynamic(get_budget_usdt, score_for_budget, float(base_price))

    qty_calc_error = None
    qty: Optional[float] = None
    try:
        qty = _calc_qty(sym, float(base_price), budget, dyn_leverage, quantity)
    except Exception as e:
        qty_calc_error = str(e)

    risk = pre_trade_risk_check(sym, side, dyn_leverage, entry)

    idem_payload = {"sym": sym, "side": side, "lev": int(dyn_leverage),
                    "qty": round(float(qty or 0), 10), "dry": bool(dry_run),
                    "entry_bucket": round(ref_for_guard, 5)}
    if not _Idem.check_and_set(idem_payload, ttl=IDEMPOTENCY_TTL_SEC):
        return {"ok": False, "reason": "idem_conflict", "ttl_sec": IDEMPOTENCY_TTL_SEC}

    # Compute TP/SL defaults when needed (pre-trail)
    if (tp is None and not tp_targets) or ((sl is None and not sl_targets) and not trail_enabled):
        tps, tps_splits, sls = _compute_tp_sl_targets(side, float(entry or base_price), kl)
        if tp is None and not tp_targets: tp_targets, tp_splits = tps, tps_splits
        if (sl is None and not sl_targets) and (not trail_enabled): sl_targets = sls

    if REQUIRE_TP_AND_SL:
        if not (tp_targets or tp is not None):
            return {"ok": False, "reason": "tp_required"}
        if not trail_enabled and not (sl_targets or sl is not None):
            return {"ok": False, "reason": "sl_required"}

    # Trailing calc (only for plan/dry-run; arming is after entry)
    trail_callback_pct: Optional[float] = None
    if trail_enabled:
        if kl:
            with suppress(Exception):
                atr_now = _atr_from_klines(kl, 14)
        else:
            atr_now = None
        trail_callback_pct = _compute_trailing_callback_pct(float(base_price), atr_now, float(trail_mult))

    if dry_run:
        plan: Dict[str, Any] = {
            "ok": True, "symbol": sym, "side": side, "leverage": dyn_leverage,
            "base_price": float(base_price), "dry_run": True,
            "entry_policy": f"HYBRID_LIMIT_STOP({ENTRY_BAND_BPS}/{STOP_BAND_BPS}bps)+MARKET_ESCALATION",
            "gate": gate, "risk": risk, "alloc_ok": qty is not None, "alloc_error": qty_calc_error,
            "guards": {"percent_price_bps": pp_bps, "slippage_guard_bps": SLIPPAGE_GUARD_BPS},
            "position_side": position_side, "reduce_only": reduce_only,
            "budget_used": float(budget or 0.0), "quality": score_for_budget,
            "adx": adx_for_lev,
            "trail": {
                "enabled": trail_enabled,
                "atr_mult": trail_mult,
                "freeze": trail_freeze_enabled,
                "callback_rate_pct": trail_callback_pct,
                "binance_limits_pct": [TRAIL_CALLBACK_MIN_PCT, TRAIL_CALLBACK_MAX_PCT],
            },
        }
        if qty is not None:
            ladders = _build_ladders(sym, side, qty,
                                     ([tp] if tp is not None else tp_targets), tp_splits,
                                     (None if trail_enabled else ([sl] if sl is not None else sl_targets)), sl_splits)
            plan.update({"qty": qty, **ladders})
            plan["entry_simulation"] = {
                "limit_around": _offset_bps(entry or base_price, (-ENTRY_BAND_BPS if side=="BUY" else +ENTRY_BAND_BPS), +1),
                "stop_around":  _offset_bps(entry or base_price, (+STOP_BAND_BPS  if side=="BUY" else -STOP_BAND_BPS ), +1),
                "escalate_after_sec": ESCALATE_AFTER_S, "escalate_slip_bps": ESCALATE_SLIP_BPS,
                "allow_market_entry": ALLOW_MARKET_ENTRY,
            }
        return plan

    if qty is None:
        return {"ok": False, "reason": qty_calc_error or "allocation_invalid"}

    must_approve = True if ENFORCE_APPROVAL_ALWAYS else bool(confirm_first)
    if must_approve:
        chat_id = int(telegram_chat_id or TELEGRAM_CHAT_ID or 0)
        if not chat_id:
            return {"ok": False, "reason": "telegram_chat_id_required"}
        payload = {"symbol": sym, "side": side, "qty": qty, "leverage": dyn_leverage, "quality": score_for_budget, "budget": float(budget or 0.0)}
        if os.getenv("APPROVE_BEFORE_GATE", "0").lower() in ("1","true","yes","on"):
            approval = await require_approval(chat_id, payload)
            if approval.get("status") != "approved":
                return {"ok": False, "status": approval.get("status"), "reason": "not_approved"}

    # Enforce quality gate after optional pre-approval
    if os.getenv("FEAT_QUALITY_ENFORCE", "1").lower() in ("1","true","yes","on") and not gate.get("enter_ok"):
        return {"ok": False, "reason": "quality_gate_rejected", "gate": gate}

    if must_approve and not (os.getenv("APPROVE_BEFORE_GATE", "0").lower() in ("1","true","yes","on")):
        chat_id = int(telegram_chat_id or TELEGRAM_CHAT_ID or 0)
        if not chat_id:
            return {"ok": False, "reason": "telegram_chat_id_required"}
        payload = {"symbol": sym, "side": side, "qty": qty, "leverage": dyn_leverage, "quality": score_for_budget, "budget": float(budget or 0.0)}
        approval = await require_approval(chat_id, payload)
        if approval.get("status") != "approved":
            return {"ok": False, "status": approval.get("status"), "reason": "not_approved"}

    # ביטול TP/SL ישנים לפני חימוש חדשים
    _cancel_old_closing_orders(sym)

    # ← מיישר מצב חשבון (Hedge/One-way) לפני שינוי מינוף/הזמנה – פותר שגיאות -4061
    with suppress(Exception):
        _ensure_runtime_position_mode()

    # עדכון מינוף (לא מפיל את הזרימה אם נכשל)
    with suppress(Exception):
        set_leverage(sym, int(dyn_leverage))

    # כניסה היברידית
    entry_res = await _place_hybrid_entry(sym, side, float(qty), float(base_price), entry, position_side)
    if not entry_res or (entry_res.get("ok") is False):
        await _tg_send(f"⚠️ <b>Entry failed</b>\n• {sym} {side}\n• Reason: <code>{entry_res.get('reason') if entry_res else 'entry_failed'}</code>")
        return {"ok": False, "reason": entry_res.get("reason", "entry_failed"), "details": entry_res}

    sanity_ok = bool(entry_res.get("sanity_ok", True))
    sanity_bps = entry_res.get("sanity_bps")

    if ENFORCE_POST_FILL_SANITY and not sanity_ok:
        rb = _safe_close_position(sym, side, float(qty), position_side=position_side)
        await _tg_send(f"⚠️ <b>Post-fill sanity failed</b> ({sanity_bps:.1f}bps)\n• {sym} {side} qty={qty}\n• Rolled back: <code>{bool(rb.get('ok'))}</code>")
        return {
            "ok": False,
            "reason": "post_fill_sanity_failed",
            "sanity_bps": sanity_bps,
            "rolled_back": True,
            "rollback": rb,
            "entry_result": entry_res,
        }

    plan: Dict[str, Any] = {
        "ok": True, "symbol": sym, "side": side, "qty": float(qty), "leverage": int(dyn_leverage),
        "base_price": float(base_price), "dry_run": False,
        "entry_policy": f"HYBRID_LIMIT_STOP({ENTRY_BAND_BPS}/{STOP_BAND_BPS}bps)+MARKET_ESCALATION",
        "gate": gate, "risk": risk, "entry_result": entry_res,
        "tp_orders": [], "sl_orders": [],
        "sanity_ok": sanity_ok, "sanity_bps": sanity_bps,
        "position_side": position_side, "reduce_only": reduce_only,
        "budget_used": float(budget or 0.0), "quality": score_for_budget,
        "adx": adx_for_lev,
        "trail": {
            "enabled": trail_enabled,
            "atr_mult": trail_mult,
            "freeze": trail_freeze_enabled,
            "callback_rate_pct": trail_callback_pct,
            "binance_limits_pct": [TRAIL_CALLBACK_MIN_PCT, TRAIL_CALLBACK_MAX_PCT],
        },
    }

    close_side = _close_side_for(side)

    # בניית סולמות TP/SL
    ladders = _build_ladders(
        sym, side, float(qty),
        ([tp] if tp is not None else tp_targets), tp_splits
        ,
        (None if trail_enabled else ([sl] if sl is not None else sl_targets)), sl_splits
    )
    plan["tp_orders"] = ladders["tp_orders"]
    plan["sl_orders"] = ladders["sl_orders"]

    def _place_with_retry(args: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return futures_create_order(**args)
        except Exception as e:
            msg = str(e).lower()
            code = getattr(e, "code", None)
            if ("reduceonly" in msg or "reduce only" in msg or "-1106" in msg or code == -1106):
                a2 = dict(args); a2.pop("reduceOnly", None)
                return futures_create_order(**a2)
            raise

    tp_success = False
    sl_success = False

    # ---- חימוש TP ----
    for idx, o in enumerate(plan["tp_orders"], start=1):
        typ = str(o.get("type")).upper()
        args: Dict[str, Any] = dict(
            symbol=sym,
            side=close_side,
            type=typ,
            workingType="MARK_PRICE",
            newClientOrderId=_coid(f"TP{idx}", sym, close_side),
        )
        eff_ps = _effective_position_side(position_side)
        if eff_ps != "BOTH":
            args["positionSide"] = eff_ps

        if "MARKET" in typ:
            args["stopPrice"] = _q_price(sym, float(o["stopPrice"]))[0]
        else:
            args["stopPrice"] = _q_price(sym, float(o["stopPrice"]))[0]
            args["price"]     = _q_price(sym, float(o.get("price", o["stopPrice"])))[0]
            args["timeInForce"] = "GTC"

        args["quantity"] = _q_qty(sym, float(o["qty"]))[0]

        is_market_trigger = typ in ("STOP_MARKET", "TAKE_PROFIT_MARKET")
        if not (is_market_trigger and eff_ps == "BOTH"):
            args["reduceOnly"] = True

        try:
            resp = _place_with_retry(args)
            o["response"] = resp
            if typ.startswith("TAKE_PROFIT"):
                tp_success = tp_success or bool(resp.get("orderId"))
        except Exception as e:
            o["response"] = {"ok": False, "error": str(e)}

    # ---- חימוש SL (trailing או סטטי) ----
    if trail_enabled:
        eff_ps = _effective_position_side(position_side)
        qty_str, _ = _q_qty(sym, float(qty))

        if trail_callback_pct is None:
            trail_callback_pct = max(TRAIL_CALLBACK_MIN_PCT, min(TRAIL_CALLBACK_MAX_PCT, 0.5))

        args: Dict[str, Any] = dict(
            symbol=sym,
            side=close_side,
            type="TRAILING_STOP_MARKET",
            callbackRate=f"{float(trail_callback_pct):.2f}",
            workingType="MARK_PRICE",
            quantity=qty_str,
            newClientOrderId=_coid("SL_TRAIL", sym, close_side),
        )

        mark_now = float(get_price(sym) or futures_mark_price(sym) or base_price)
        activation = _offset_bps(mark_now, (-STOP_BAND_BPS if side == "BUY" else +STOP_BAND_BPS), +1)
        args["activationPrice"] = _q_price(sym, float(activation))[0]

        if eff_ps != "BOTH":
            args["positionSide"] = eff_ps
            args["reduceOnly"] = True

        try:
            resp = _place_with_retry(args)
            plan["sl_orders"].append({
                "type": "TRAILING_STOP_MARKET",
                "callbackRate": float(trail_callback_pct),
                "activationPrice": args["activationPrice"],
                "qty": float(qty),
                "response": resp,
            })
            sl_success = sl_success or bool(resp.get("orderId"))
        except Exception as e:
            plan["sl_orders"].append({
                "type": "TRAILING_STOP_MARKET",
                "callbackRate": float(trail_callback_pct),
                "activationPrice": args.get("activationPrice"),
                "qty": float(qty),
                "response": {"ok": False, "error": str(e)},
            })
    else:
        for idx, o in enumerate(plan["sl_orders"], start=1):
            typ = str(o.get("type")).upper()
            args: Dict[str, Any] = dict(
                symbol=sym,
                side=close_side,
                type=typ,
                workingType="MARK_PRICE",
                newClientOrderId=_coid(f"SL{idx}", sym, close_side),
            )
            eff_ps = _effective_position_side(position_side)
            if eff_ps != "BOTH":
                args["positionSide"] = eff_ps

            if "MARKET" in typ:
                args["stopPrice"] = _q_price(sym, float(o["stopPrice"]))[0]
            else:
                args["stopPrice"] = _q_price(sym, float(o["stopPrice"]))[0]
                args["price"]     = _q_price(sym, float(o.get("price", o["stopPrice"])))[0]
                args["timeInForce"] = "GTC"

            args["quantity"] = _q_qty(sym, float(o["qty"]))[0]

            is_market_trigger = typ in ("STOP_MARKET", "TAKE_PROFIT_MARKET")
            if not (is_market_trigger and eff_ps == "BOTH"):
                args["reduceOnly"] = True

            try:
                resp = _place_with_retry(args)
                o["response"] = resp
                if typ.startswith("STOP"):
                    sl_success = sl_success or bool(resp.get("orderId"))
            except Exception as e:
                o["response"] = {"ok": False, "error": str(e)}

    if REQUIRE_TP_AND_SL and not (tp_success and (sl_success or trail_enabled)):
        rb = _safe_close_position(sym, side, float(qty), position_side=position_side)
        plan.update({
            "ok": False,
            "reason": "tp_sl_arming_failed",
            "rolled_back": True,
            "rollback": rb,
        })
        await _tg_send(f"⚠️ <b>Arming TP/SL failed</b>\n• {sym} {side} qty={qty}\n• rolled_back={bool(rb.get('ok'))}")
        return plan

    # הודעה ל-טלגרם על כניסה + חימוש
    try:
        tp_cnt = sum(1 for o in plan["tp_orders"] if isinstance(o.get("response", {}).get("orderId"), (int, str)))
        sl_cnt = sum(1 for o in plan["sl_orders"] if isinstance(o.get("response", {}).get("orderId"), (int, str)))
        entry_kind = plan["entry_result"].get("entry_kind")
        entry_px   = plan["entry_result"].get("price")
        await _tg_send(
            "✅ <b>Trade armed</b>\n"
            f"• {sym} {side} qty={qty} lev={dyn_leverage}\n"
            f"• Entry: <code>{entry_kind}@{entry_px}</code>\n"
            f"• TP armed: <code>{tp_cnt}</code> · SL armed: <code>{'trail' if trail_enabled else sl_cnt}</code>"
        )
    except Exception:
        pass

    return plan

# ─────────── Rollback helper ───────────
def _safe_close_position(sym: str, side: str, qty: float, position_side: str = "BOTH") -> Dict[str, Any]:
    eff_ps = _effective_position_side(_normalize_position_side(position_side))
    close_side = _close_side_for(side)
    args = dict(
        symbol=sym,
        side=close_side,
        type="MARKET",
        quantity=_q_qty(sym, float(qty))[0],
        newClientOrderId=_coid("RBK", sym, close_side),
    )
    if eff_ps != "BOTH":
        args["positionSide"] = eff_ps
        args["reduceOnly"] = True  # Hedge תקין
    try:
        return {"ok": True, "response": futures_create_order(**args)}
    except Exception as e:
        msg = str(e).lower()
        if "reduceonly" in msg or "reduce only" in msg or "-1106" in msg or getattr(e, "code", None) == -1106:
            args2 = dict(args); args2.pop("reduceOnly", None)
            try:
                return {"ok": True, "response": futures_create_order(**args2)}
            except Exception as e2:
                return {"ok": False, "error": str(e2)}
        return {"ok": False, "error": str(e)}

__all__ = [
    "execute_trade_live",
    "ConfirmStore",
    "send_confirm_request",
    "require_approval",
]



































































































