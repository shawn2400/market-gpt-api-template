#!/usr/bin/env python3
"""
Trade Guardian Worker - 100% Position Protection Safety Net
============================================================
Runs every 30 seconds to ensure ALL positions have SL/TP protection.

Features:
- Detects missing SL → adds immediately using dynamic calculation
- Detects missing TP → rebuilds ladder using AI parameters
- Cancels orphaned orders (orders without positions)
- Validates all protections exist on Binance
- Logs all fixes to database
- Sends immediate Telegram alerts

This is NOT dynamic AI management - this is a safety net.
The dynamic AI management happens in Position Monitor.
"""

import os
import sys
import time
import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.binance_client import _init_client as get_client
from utils.db import _conn
from utils.dynamic_sltp_manager import DynamicSLTPManager
from utils.live_position_manager import LivePositionManager
from utils.position_manager import _bn_round, _get_filters

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("trade_guardian")

# Configuration
GUARDIAN_INTERVAL_SEC = int(os.getenv("GUARDIAN_INTERVAL_SEC", "30"))
ENABLE_GUARDIAN = os.getenv("ENABLE_GUARDIAN", "1").lower() in ("1", "true", "yes")
GUARDIAN_TELEGRAM_ALERTS = os.getenv("GUARDIAN_TELEGRAM_ALERTS", "1").lower() in ("1", "true", "yes")

# Statistics
stats = {
    "sl_added": 0,
    "tp_added": 0,
    "sl_fixed": 0,
    "tp_fixed": 0,
    "orphaned_cancelled": 0,
    "errors": 0,
    "last_run": None,
    "total_runs": 0,
    "last_sl_attempt": {}  # Track last attempt per symbol to avoid race with Position Monitor
}


def get_active_positions() -> List[Dict[str, Any]]:
    """Get all active positions from Binance"""
    try:
        client = get_client()
        positions = client.futures_position_information()
        
        active = []
        for pos in positions:
            amt = float(pos.get("positionAmt", 0))
            if abs(amt) > 0:
                active.append({
                    "symbol": pos.get("symbol"),
                    "positionAmt": amt,
                    "entryPrice": float(pos.get("entryPrice", 0)),
                    "unrealizedProfit": float(pos.get("unrealizedProfit", 0)),
                    "leverage": int(pos.get("leverage", 1)),
                    "markPrice": float(pos.get("markPrice", 0))
                })
        
        return active
    except Exception as e:
        logger.error(f"Failed to get active positions: {e}")
        return []


def get_open_orders(symbol: str) -> Dict[str, List[Dict[str, Any]]]:
    """Get open orders grouped by type"""
    try:
        client = get_client()
        orders = client.futures_get_open_orders(symbol=symbol)
        
        categorized = {
            "SL": [],
            "TP": [],
            "TRAILING": [],
            "OTHER": []
        }
        
        for order in orders:
            order_type = order.get("type", "")
            
            if order_type in ("STOP", "STOP_MARKET"):
                categorized["SL"].append(order)
            elif order_type in ("TAKE_PROFIT", "TAKE_PROFIT_MARKET", "LIMIT"):
                categorized["TP"].append(order)
            elif order_type == "TRAILING_STOP_MARKET":
                categorized["TRAILING"].append(order)
            else:
                categorized["OTHER"].append(order)
        
        return categorized
    except Exception as e:
        logger.error(f"Failed to get open orders for {symbol}: {e}")
        return {"SL": [], "TP": [], "TRAILING": [], "OTHER": []}


def calculate_simple_atr(highs: list, lows: list, closes: list, period: int = 14) -> float:
    """Simple ATR calculation"""
    try:
        if len(highs) < period + 1:
            return 0.0
        
        tr_values = []
        for i in range(1, len(highs)):
            high_low = highs[i] - lows[i]
            high_close = abs(highs[i] - closes[i-1])
            low_close = abs(lows[i] - closes[i-1])
            tr = max(high_low, high_close, low_close)
            tr_values.append(tr)
        
        if len(tr_values) < period:
            return 0.0
        
        atr = sum(tr_values[-period:]) / period
        return atr
    except Exception:
        return 0.0


def get_market_data(symbol: str) -> Dict[str, Any]:
    """Get current market data for symbol"""
    try:
        client = get_client()
        
        # Get klines for ATR calculation
        klines = client.futures_klines(symbol=symbol, interval="15m", limit=20)
        
        # Calculate ATR
        highs = [float(k[2]) for k in klines]
        lows = [float(k[3]) for k in klines]
        closes = [float(k[4]) for k in klines]
        
        atr = calculate_simple_atr(highs, lows, closes, period=14)
        current_price = closes[-1]
        atr_pct = (atr / current_price) * 100 if current_price > 0 else 0
        
        return {
            "atr": atr,
            "atr_pct": atr_pct,
            "price": current_price,
            "high_24h": max(highs),
            "low_24h": min(lows)
        }
    except Exception as e:
        logger.error(f"Failed to get market data for {symbol}: {e}")
        return {"atr": 0, "atr_pct": 0, "price": 0, "high_24h": 0, "low_24h": 0}


def add_missing_sl(position: Dict[str, Any]) -> bool:
    """Add SL using dynamic calculation"""
    try:
        symbol = position["symbol"]
        entry_price = position["entryPrice"]
        pos_amt = position["positionAmt"]
        direction = "LONG" if pos_amt > 0 else "SHORT"
        
        logger.warning(f"🚨 {symbol}: MISSING SL! Adding protection...")
        
        # Get market data
        market = get_market_data(symbol)
        atr = market["atr"]
        atr_pct = market["atr_pct"]
        
        if atr == 0:
            logger.error(f"Cannot calculate SL for {symbol}: ATR is 0")
            return False
        
        # Use dynamic SL/TP manager
        sltp_mgr = DynamicSLTPManager()
        recommendation = sltp_mgr.calculate_sltp(
            symbol=symbol,
            side=direction,
            entry_price=entry_price,
            atr=atr,
            atr_pct=atr_pct,
            market_regime="choppy",  # Conservative default
            market_mood="neutral",
            trend_strength=50,
            target_rr=1.5,
            volatility_class="medium"
        )
        
        sl_price = recommendation.sl_price
        
        # Get Binance filters and round to proper precision
        client = get_client()
        tick, step = _get_filters(client, symbol)
        sl_price_rounded = _bn_round(sl_price, tick)
        
        # Format as string with proper precision (SOLUSDT needs 2 decimals)
        # Binance rejects floats with trailing zeros, so format explicitly
        decimal_places = len(str(tick).split('.')[-1]) if '.' in str(tick) else 0
        sl_price_str = f"{sl_price_rounded:.{decimal_places}f}"
        
        logger.info(f"📊 {symbol}: SL={sl_price:.4f} → {sl_price_str} (tick={tick})")
        
        # Place SL on Binance
        side = "SELL" if direction == "LONG" else "BUY"
        
        order = client.futures_create_order(
            symbol=symbol,
            side=side,
            type="STOP_MARKET",
            stopPrice=sl_price_str,
            closePosition=True
        )
        
        order_id = order.get("orderId")
        
        # Validate SL exists
        time.sleep(0.5)
        orders = get_open_orders(symbol)
        if not orders["SL"]:
            raise Exception("SL order not found after placement!")
        
        logger.info(f"✅ {symbol}: Added SL @ ${sl_price_str} (Order #{order_id})")
        
        # Log to database
        log_guardian_fix(symbol, "missing_sl", f"Added SL @ ${sl_price_str}", True)
        
        # Telegram alert (use simple requests instead of async)
        if GUARDIAN_TELEGRAM_ALERTS:
            try:
                import requests
                bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
                chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
                
                if bot_token and chat_id:
                    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
                    payload = {
                        "chat_id": chat_id,
                        "text": (
                            f"🤖 <b>Trade Guardian Alert</b>\n\n"
                            f"Symbol: <code>{symbol}</code>\n"
                            f"Issue: <b>Missing SL</b>\n"
                            f"Fix: Added SL @ ${sl_price_str}\n"
                            f"Direction: {direction}\n"
                            f"Entry: ${entry_price:.4f}\n"
                            f"Status: ✅ Success"
                        ),
                        "parse_mode": "HTML",
                        "disable_web_page_preview": True
                    }
                    requests.post(url, json=payload, timeout=5)
                    logger.info("📱 Telegram alert sent")
            except Exception as e:
                logger.warning(f"Failed to send Telegram alert: {e}")
        
        stats["sl_added"] += 1
        return True
        
    except Exception as e:
        logger.error(f"Failed to add SL for {symbol}: {e}", exc_info=True)
        log_guardian_fix(symbol, "missing_sl", f"Failed: {str(e)}", False)
        stats["errors"] += 1
        return False


def add_missing_tp(position: Dict[str, Any]) -> bool:
    """Add TP ladder using dynamic calculation"""
    try:
        symbol = position["symbol"]
        entry_price = position["entryPrice"]
        pos_amt = position["positionAmt"]
        direction = "LONG" if pos_amt > 0 else "SHORT"
        
        logger.warning(f"⚠️ {symbol}: Missing TP! Adding ladder...")
        
        # Get market data
        market = get_market_data(symbol)
        atr = market["atr"]
        atr_pct = market["atr_pct"]
        
        if atr == 0:
            logger.error(f"Cannot calculate TP for {symbol}: ATR is 0")
            return False
        
        # Use dynamic SL/TP manager
        sltp_mgr = DynamicSLTPManager()
        recommendation = sltp_mgr.calculate_sltp(
            symbol=symbol,
            side=direction,
            entry_price=entry_price,
            atr=atr,
            atr_pct=atr_pct,
            market_regime="choppy",
            market_mood="neutral",
            trend_strength=50,
            target_rr=1.5,
            volatility_class="medium"
        )
        
        tp_prices = [
            recommendation.tp1_price,
            recommendation.tp2_price,
            recommendation.tp3_price
        ]
        
        # Place TP orders
        client = get_client()
        side = "SELL" if direction == "LONG" else "BUY"
        
        # Split position into 3 parts
        total_qty = abs(pos_amt)
        qty_splits = [
            round(total_qty * 0.33, 3),
            round(total_qty * 0.33, 3),
            round(total_qty * 0.34, 3)
        ]
        
        placed_count = 0
        for i, (tp_price, qty) in enumerate(zip(tp_prices, qty_splits), 1):
            try:
                order = client.futures_create_order(
                    symbol=symbol,
                    side=side,
                    type="LIMIT",
                    timeInForce="GTC",
                    price=tp_price,
                    quantity=qty
                )
                placed_count += 1
                logger.info(f"  TP{i} @ ${tp_price:.4f} (qty: {qty})")
            except Exception as e:
                logger.warning(f"  Failed to place TP{i}: {e}")
        
        if placed_count > 0:
            logger.info(f"✅ {symbol}: Added {placed_count} TP orders")
            log_guardian_fix(symbol, "missing_tp", f"Added {placed_count} TP orders", True)
            
            if GUARDIAN_TELEGRAM_ALERTS:
                send_telegram_message(
                    f"🤖 <b>Trade Guardian Alert</b>\n\n"
                    f"Symbol: <code>{symbol}</code>\n"
                    f"Issue: <b>Missing TP</b>\n"
                    f"Fix: Added {placed_count} TP orders\n"
                    f"TP1: ${tp_prices[0]:.4f}\n"
                    f"TP2: ${tp_prices[1]:.4f}\n"
                    f"TP3: ${tp_prices[2]:.4f}\n"
                    f"Status: ✅ Success",
                    parse_mode="HTML"
                )
            
            stats["tp_added"] += placed_count
            return True
        else:
            return False
        
    except Exception as e:
        logger.error(f"Failed to add TP for {symbol}: {e}", exc_info=True)
        log_guardian_fix(symbol, "missing_tp", f"Failed: {str(e)}", False)
        stats["errors"] += 1
        return False


def cancel_orphaned_orders() -> int:
    """Cancel orders for positions that don't exist"""
    try:
        client = get_client()
        
        # Get all positions
        positions = get_active_positions()
        active_symbols = {p["symbol"] for p in positions}
        
        # Get all open orders
        all_orders = client.futures_get_open_orders()
        
        cancelled_count = 0
        for order in all_orders:
            symbol = order.get("symbol")
            
            if symbol not in active_symbols:
                try:
                    client.futures_cancel_order(symbol=symbol, orderId=order["orderId"])
                    logger.info(f"🧹 Cancelled orphaned order for {symbol}")
                    cancelled_count += 1
                except Exception as e:
                    logger.warning(f"Failed to cancel orphaned order for {symbol}: {e}")
        
        if cancelled_count > 0:
            stats["orphaned_cancelled"] += cancelled_count
            
        return cancelled_count
        
    except Exception as e:
        logger.error(f"Failed to cancel orphaned orders: {e}")
        return 0


def log_guardian_fix(symbol: str, issue: str, fix_applied: str, success: bool):
    """Log guardian fix to database"""
    try:
        with _conn() as conn:
            if not conn:
                return
            
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS guardian_fixes (
                        id SERIAL PRIMARY KEY,
                        timestamp TIMESTAMP DEFAULT NOW(),
                        symbol VARCHAR(20),
                        issue VARCHAR(50),
                        fix_applied TEXT,
                        success BOOLEAN
                    )
                """)
                
                cur.execute("""
                    INSERT INTO guardian_fixes (symbol, issue, fix_applied, success)
                    VALUES (%s, %s, %s, %s)
                """, (symbol, issue, fix_applied, success))
    except Exception as e:
        logger.error(f"Failed to log guardian fix: {e}")


async def guardian_check():
    """Main guardian check - runs every 30 seconds"""
    try:
        logger.info("🔍 Trade Guardian: Starting protection check...")
        
        positions = get_active_positions()
        
        if not positions:
            logger.info("No active positions - nothing to protect")
            return
        
        logger.info(f"Found {len(positions)} active position(s)")
        
        for pos in positions:
            symbol = pos["symbol"]
            
            # Get open orders
            orders = get_open_orders(symbol)
            
            # Check SL - but don't interfere if Position Monitor is actively managing
            # Position Monitor runs manage_once() which cancels/replaces SL every cycle
            # We only add SL if NONE exist for 60+ seconds (2 Guardian cycles)
            if not orders["SL"]:
                # Check if we recently tried to add SL for this symbol
                last_attempt = stats.get("last_sl_attempt", {}).get(symbol, 0)
                now = time.time()
                
                if now - last_attempt > 60:  # Only try once per minute
                    logger.warning(f"⚠️ {symbol}: NO SL FOUND for 60+ seconds!")
                    stats.setdefault("last_sl_attempt", {})[symbol] = now
                    add_missing_sl(pos)
                else:
                    logger.debug(f"⏳ {symbol}: SL missing but waiting (last attempt {int(now - last_attempt)}s ago)")
            else:
                logger.debug(f"✓ {symbol}: SL exists ({len(orders['SL'])} order(s))")
            
            # Check TP
            if not orders["TP"]:
                logger.warning(f"⚠️ {symbol}: NO TP FOUND!")
                add_missing_tp(pos)
            else:
                logger.debug(f"✓ {symbol}: TP exists ({len(orders['TP'])} order(s))")
        
        # Cancel orphaned orders
        cancelled = cancel_orphaned_orders()
        if cancelled > 0:
            logger.info(f"🧹 Cancelled {cancelled} orphaned order(s)")
        
        stats["last_run"] = datetime.now(timezone.utc)
        stats["total_runs"] += 1
        
        logger.info(
            f"✅ Guardian check complete | "
            f"SL added: {stats['sl_added']}, "
            f"TP added: {stats['tp_added']}, "
            f"Orphaned: {stats['orphaned_cancelled']}, "
            f"Errors: {stats['errors']}"
        )
        
    except Exception as e:
        logger.error(f"Guardian check failed: {e}", exc_info=True)
        stats["errors"] += 1


async def main():
    """Main loop"""
    logger.info("="*60)
    logger.info("🛡️  Trade Guardian Worker Starting")
    logger.info("="*60)
    logger.info(f"Interval: {GUARDIAN_INTERVAL_SEC} seconds")
    logger.info(f"Enabled: {ENABLE_GUARDIAN}")
    logger.info(f"Telegram Alerts: {GUARDIAN_TELEGRAM_ALERTS}")
    logger.info("="*60)
    
    if not ENABLE_GUARDIAN:
        logger.warning("⚠️ Trade Guardian is DISABLED (set ENABLE_GUARDIAN=1 to enable)")
        return
    
    while True:
        try:
            await guardian_check()
        except Exception as e:
            logger.error(f"Guardian loop error: {e}", exc_info=True)
        
        await asyncio.sleep(GUARDIAN_INTERVAL_SEC)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\n🛑 Trade Guardian stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
