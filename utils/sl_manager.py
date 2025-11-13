# utils/sl_manager.py
"""
Zero-Gap Stop Loss Manager with Smart Position Mode Compatibility.
Ensures positions are never left unprotected when updating SL.
Strategy: place new SL → verify → cancel old SL

✅ Supports both Hedge Mode (LONG/SHORT) and One-Way Mode (BOTH)
🛡️ Time-Based Protection: Prevents ultra-short trades (8-second exits)
🎯 GRID Protection: Special 30-minute hold time for GRID trades
"""
from __future__ import annotations
import logging
import time
import os
from typing import Optional, Dict, Any

log = logging.getLogger(__name__)

# Import time protection constants
try:
    from utils.trade_execution_core import MIN_TRADE_HOLD_TIME_SEC, GRID_MIN_HOLD_TIME_SEC
except ImportError:
    MIN_TRADE_HOLD_TIME_SEC = 60  # 60s minimum
    GRID_MIN_HOLD_TIME_SEC = 1800  # 30 min for GRID


def _get_position_entry_time(symbol: str) -> Optional[float]:
    """
    Query database for position entry time (ts_open).
    Works with both PostgreSQL and SQLite using utils.db abstraction.
    
    Returns:
        Timestamp (seconds since epoch) or None if not found
    """
    try:
        from utils.db import _conn, _is_postgres, DB_URL
        
        if not DB_URL:
            log.debug(f"[TimeProtection] Database not configured")
            return None
        
        is_pg = _is_postgres(DB_URL)
        
        with _conn() as con:
            cursor = con.cursor()
            
            if is_pg:
                # PostgreSQL: EXTRACT(EPOCH FROM timestamp)
                cursor.execute("""
                    SELECT EXTRACT(EPOCH FROM ts_open)
                    FROM positions
                    WHERE symbol = %s AND status = 'OPEN'
                    ORDER BY ts_open DESC
                    LIMIT 1
                """, (symbol,))
            else:
                # SQLite: ts_open is already stored as REAL (unix timestamp)
                cursor.execute("""
                    SELECT ts_open
                    FROM positions
                    WHERE symbol = ? AND status = 'OPEN'
                    ORDER BY ts_open DESC
                    LIMIT 1
                """, (symbol,))
            
            row = cursor.fetchone()
            
            if row and row[0]:
                entry_ts = float(row[0])
                log.debug(f"[TimeProtection] {symbol} entry time: {entry_ts} ({time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(entry_ts))})")
                return entry_ts
            else:
                log.debug(f"[TimeProtection] No open position found for {symbol}")
                return None
            
    except Exception as e:
        log.warning(f"[TimeProtection] Failed to get entry time for {symbol}: {e}")
        return None


def _check_minimum_hold_time(symbol: str, is_grid: bool = False) -> tuple[bool, str]:
    """
    Check if position has been held for minimum required time.
    
    Args:
        symbol: Trading pair
        is_grid: Whether this is a GRID trade (requires longer hold time)
    
    Returns:
        (allow_update: bool, reason: str)
    """
    entry_ts = _get_position_entry_time(symbol)
    
    if entry_ts is None:
        # If we can't determine entry time, allow update (fail-open for safety)
        log.warning(f"[TimeProtection] {symbol} - Cannot determine entry time, allowing SL update")
        return True, "entry_time_unknown"
    
    now = time.time()
    elapsed_sec = now - entry_ts
    min_hold_time = GRID_MIN_HOLD_TIME_SEC if is_grid else MIN_TRADE_HOLD_TIME_SEC
    
    if elapsed_sec < min_hold_time:
        elapsed_min = int(elapsed_sec / 60)
        required_min = int(min_hold_time / 60)
        trade_type = "GRID" if is_grid else "regular"
        reason = f"{trade_type} trade must be held for {required_min} min (current: {elapsed_min} min)"
        log.warning(f"[TimeProtection] ⚠️ {symbol} - {reason}")
        return False, reason
    
    log.info(f"[TimeProtection] ✅ {symbol} - Minimum hold time satisfied ({int(elapsed_sec)}s elapsed)")
    return True, "time_check_passed"


class ZeroGapSLManager:
    """
    Manages Stop Loss updates with zero-gap protection.
    Never leaves a position without protective stop.
    """

    def __init__(self, binance_client):
        """
        Args:
            binance_client: Module with futures_create_order, futures_cancel_order, get_open_orders
        """
        self.client = binance_client

    def safe_replace_sl(
        self,
        symbol: str,
        new_stop_price: float,
        qty: float,
        side: str,  # "LONG" or "SHORT"
        position_side: Optional[str] = None,
        max_verify_attempts: int = 3,
        is_grid: bool = False,  # 🎯 NEW: GRID trades require longer hold time
    ) -> Dict[str, Any]:
        """
        Replace existing SL with new one using zero-gap strategy.

        Steps:
        0. 🛡️ Check minimum hold time (prevents ultra-short exits)
        1. Place new STOP_MARKET order
        2. Verify it's active
        3. Cancel old SL orders
        4. Verify old ones cancelled

        Args:
            symbol: Trading pair (e.g., "BTCUSDT")
            new_stop_price: New stop loss price
            qty: Position quantity (absolute value)
            side: Position side ("LONG" or "SHORT")
            position_side: Hedge mode position side
            max_verify_attempts: Max attempts to verify order placement
            is_grid: Whether this is a GRID trade (requires 30 min hold vs 60s)

        Returns:
            {"success": bool, "new_order_id": int, "cancelled_count": int, "error": str}
        """
        try:
            # 🛡️ Step 0: Check minimum hold time (TIME-BASED PROTECTION)
            allow_update, time_reason = _check_minimum_hold_time(symbol, is_grid=is_grid)
            if not allow_update:
                log.warning(f"[ZeroGapSL] {symbol} SL update blocked: {time_reason}")
                return {
                    "success": False,
                    "error": f"Time protection: {time_reason}",
                    "new_order_id": None,
                    "cancelled_count": 0,
                    "time_blocked": True
                }
            
            # Determine order side (opposite of position)
            order_side = "SELL" if side == "LONG" else "BUY"

            # Step 1: Place new SL
            log.info(f"[ZeroGapSL] {symbol} placing new SL @ {new_stop_price} ({side})")
            
            # Build base order kwargs
            order_kwargs = {
                "symbol": symbol,
                "side": order_side,
                "type": "STOP_MARKET",
                "quantity": qty,
                "stopPrice": new_stop_price,
                "reduceOnly": True,  # CRITICAL: Prevent opening new positions
                "newClientOrderId": f"SL_{symbol}_{int(time.time())}",
            }
            
            # ✅ SMART POSITION MODE COMPATIBILITY
            # Add positionSide ONLY in Hedge Mode (LONG/SHORT)
            # In One-Way Mode, position_side='BOTH' and must be OMITTED
            if position_side and position_side in ("LONG", "SHORT"):
                order_kwargs["positionSide"] = position_side
                log.debug(f"[ZeroGapSL] {symbol} Hedge Mode: positionSide={position_side}, reduceOnly=True")
            else:
                log.debug(f"[ZeroGapSL] {symbol} One-Way Mode: position_side={position_side}, reduceOnly=True")
            
            new_order = self.client.futures_create_order(**order_kwargs)

            if not new_order or "orderId" not in new_order:
                return {"success": False, "error": "Failed to place new SL", "new_order_id": None, "cancelled_count": 0}

            new_order_id = new_order["orderId"]

            # Step 2: Verify new SL is active
            verified = False
            for attempt in range(max_verify_attempts):
                time.sleep(0.3)  # Brief delay
                open_orders = self.client.futures_get_open_orders(symbol=symbol) or []
                for o in open_orders:
                    if o.get("orderId") == new_order_id:
                        status = (o.get("status") or "").upper()
                        if status in ("NEW", "PARTIALLY_FILLED"):
                            verified = True
                            break
                if verified:
                    break
                log.warning(f"[ZeroGapSL] {symbol} verify attempt {attempt + 1}/{max_verify_attempts}")

            if not verified:
                log.error(f"[ZeroGapSL] {symbol} new SL not verified, aborting cancellation")
                return {
                    "success": False,
                    "error": "New SL not verified",
                    "new_order_id": new_order_id,
                    "cancelled_count": 0,
                }

            # Step 3: Cancel old SL orders (exclude the new one)
            log.info(f"[ZeroGapSL] {symbol} new SL verified, cancelling old SLs")
            open_orders = self.client.futures_get_open_orders(symbol=symbol) or []
            cancelled_count = 0
            for o in open_orders:
                oid = o.get("orderId")
                if oid == new_order_id:
                    continue  # Don't cancel the new one
                otype = (o.get("type") or "").upper()
                if "STOP" not in otype:
                    continue
                # Check position side match (for Hedge mode)
                if position_side:
                    order_pos_side = (o.get("positionSide") or "").upper()
                    if order_pos_side and order_pos_side != position_side.upper():
                        continue
                try:
                    self.client.futures_cancel_order(symbol=symbol, orderId=oid)
                    cancelled_count += 1
                    log.info(f"[ZeroGapSL] {symbol} cancelled old SL order {oid}")
                except Exception as e:
                    log.warning(f"[ZeroGapSL] {symbol} failed to cancel {oid}: {e}")

            # Step 4: Verify old orders are gone
            time.sleep(0.2)
            remaining_orders = self.client.futures_get_open_orders(symbol=symbol) or []
            remaining_stop_count = 0
            for o in remaining_orders:
                if o.get("orderId") == new_order_id:
                    continue
                otype = (o.get("type") or "").upper()
                if "STOP" in otype:
                    if position_side:
                        order_pos_side = (o.get("positionSide") or "").upper()
                        if order_pos_side == position_side.upper():
                            remaining_stop_count += 1
                    else:
                        remaining_stop_count += 1

            if remaining_stop_count > 0:
                log.warning(f"[ZeroGapSL] {symbol} still has {remaining_stop_count} old SL orders")

            log.info(f"[ZeroGapSL] {symbol} ✅ SL update complete (new: {new_order_id}, cancelled: {cancelled_count})")
            return {
                "success": True,
                "new_order_id": new_order_id,
                "cancelled_count": cancelled_count,
                "error": None,
            }

        except Exception as e:
            log.error(f"[ZeroGapSL] {symbol} error: {e}")
            return {"success": False, "error": str(e), "new_order_id": None, "cancelled_count": 0}
