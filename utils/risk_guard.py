# utils/risk_guard.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import os
import logging
from datetime import datetime
from typing import Tuple, Dict, Any, List

logger = logging.getLogger("algogpt.risk_guard")

# ──────────────────────────────────────────────────────────────────────────────
# Fallback shims (so the module is safe to import even if deps are missing)
# ──────────────────────────────────────────────────────────────────────────────
try:
    from utils.pnl_summary import get_pnl_summary  # type: ignore
except Exception:  # pragma: no cover
    def get_pnl_summary(limit_days: int = 1) -> Dict[str, Any]:  # type: ignore
        """
        Fallback: return an empty day list.
        Expected schema (when available):
          { "days": [ { "day": "YYYY-MM-DD", "pnl": float, ... }, ... ] }
        """
        return {"days": []}

try:
    from utils.trade_store import list_active  # type: ignore
except Exception:  # pragma: no cover
    def list_active() -> List[Dict[str, Any]]:  # type: ignore
        """
        Fallback: no active trades.
        Expected schema for each trade (when available):
          { "symbol": "BTCUSDT", ... }
        """
        return []


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────
def _to_bool(v: str, default: bool = False) -> bool:
    try:
        return str(v).strip().lower() in ("1", "true", "yes", "on")
    except Exception:
        return default


def _to_float(v: str, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default


def _to_int(v: str, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return default


def _get_env_flags() -> Dict[str, Any]:
    """
    Collect risk toggles with safe parsing and backwards-compatible env names.
    """
    return {
        # Global kill-switch for new trades
        "GLOBAL_OFF": _to_bool(os.getenv("GLOBAL_RISK_OFF", "0")),
        # Daily loss cap (uses DAILY_NET_LOSS_USD_MAX if set, otherwise DAILY_LOSS_CAP_USDT)
        "DAILY_MAX_LOSS": _to_float(
            os.getenv("DAILY_NET_LOSS_USD_MAX", os.getenv("DAILY_LOSS_CAP_USDT", "0") or "0"),
            default=0.0,
        ),
        # Concurrent trades cap per symbol
        "MAX_OPEN_PER_SYMBOL": _to_int(
            os.getenv("MAX_CONCURRENT_TRADES_PER_SYMBOL", os.getenv("MAX_OPEN_PER_SYMBOL", "0") or "0"),
            default=0,
        ),
    }


def _extract_today_loss(pnl_obj: Dict[str, Any]) -> float:
    """
    Try to read today's PnL (negative = loss) from a flexible summary schema.
    Accepts keys: 'pnl', 'net', 'net_usd', or sum of ['realized', 'unrealized'] if present.
    Returns 0.0 if not found/parsable.
    """
    try:
        day_str = datetime.utcnow().strftime("%Y-%m-%d")
        # try to find today's row by 'day' or 'date'
        days: List[Dict[str, Any]] = pnl_obj.get("days") or []
        today_row = None
        for d in days:
            if str(d.get("day") or d.get("date")) == day_str:
                today_row = d
                break
        if not today_row:
            return 0.0

        # Prefer common keys
        for k in ("pnl", "net", "net_usd"):
            if k in today_row:
                return float(today_row.get(k) or 0.0)

        # Fallback: sum realized + unrealized if present
        realized = today_row.get("realized")
        unreal = today_row.get("unrealized")
        if realized is not None or unreal is not None:
            r = float(realized or 0.0)
            u = float(unreal or 0.0)
            return r + u
    except Exception:
        pass
    return 0.0


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────
def allow_new_trade(symbol: str) -> Tuple[bool, str]:
    """
    Lightweight risk gate:
      1) Global off switch (GLOBAL_RISK_OFF=1) → block
      2) Max concurrent open trades per symbol (MAX_CONCURRENT_TRADES_PER_SYMBOL) → block when reached
      3) Daily loss cap based on get_pnl_summary() (DAILY_NET_LOSS_USD_MAX or DAILY_LOSS_CAP_USDT) → block when exceeded

    Returns:
      (allowed: bool, reason: str)
      Where reason is either "OK" or the blocking reason key.
    """
    env = _get_env_flags()

    # 1) Global switch
    if env["GLOBAL_OFF"]:
        logger.warning("🚫 Trade blocked: GLOBAL_RISK_OFF=1")
        return (False, "GLOBAL_RISK_OFF")

    # Normalize symbol
    sym = (symbol or "").upper().strip()

    # 2) Concurrent-per-symbol cap (0 or negative = disabled)
    try:
        max_open = int(env["MAX_OPEN_PER_SYMBOL"] or 0)
        if max_open > 0:
            active = list_active() or []
            cnt = 0
            for t in active:
                try:
                    if str(t.get("symbol", "")).upper().strip() == sym:
                        cnt += 1
                except Exception:
                    continue
            if cnt >= max_open:
                logger.warning(
                    "🚫 Trade blocked: MAX_CONCURRENT_TRADES_PER_SYMBOL reached (%s) for %s [active=%s]",
                    max_open, sym, cnt
                )
                return (False, f"MAX_CONCURRENT_TRADES_PER_SYMBOL={max_open}")
    except Exception as e:
        logger.error("risk_guard.list_active failed: %s", e)

    # 3) Daily loss cap (0 or negative = disabled)
    try:
        cap = float(env["DAILY_MAX_LOSS"] or 0.0)
    except Exception:
        cap = 0.0

    if cap > 0.0:
        try:
            pnl = get_pnl_summary(limit_days=1) or {}
            today_loss = _extract_today_loss(pnl)
            # If today_loss is negative and beyond cap → block
            if today_loss < 0 and abs(today_loss) > cap:
                logger.warning(
                    "🚫 Trade blocked: DAILY_NET_LOSS cap hit (cap=%.2f, loss=%.2f) for %s",
                    cap, today_loss, sym
                )
                return (False, f"DAILY_NET_LOSS_USD_MAX={cap}")
        except Exception as e:
            # Don't block if summary is unavailable – be permissive but log an error
            logger.error("risk_guard.get_pnl_summary failed (permissive allow): %s", e)

    return (True, "OK")


__all__ = ["allow_new_trade"]

