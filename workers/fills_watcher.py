# workers/fills_watcher.py
from __future__ import annotations
import os
import time
import logging
import threading
import asyncio
from typing import Dict, Any, Optional, List, Tuple
from dotenv import load_dotenv

load_dotenv()

from utils.metrics_prom import inc_fill, set_rr, inc_profit_lock, observe_ttp1
from utils.rr import rr_now

log = logging.getLogger("algogpt.fills_watcher")

# Import trade manager for dynamic SL/TP/BE management
try:
    from utils.trade_manager import manage_open_trades
except Exception:
    async def manage_open_trades():  # type: ignore
        log.debug("trade_manager unavailable")
        pass

# Import Multi-Target TP for dynamic TP extension
try:
    from utils.multi_target_tp import get_multi_target_tp
    from utils.binance_client import futures_create_order, get_klines
    from utils.binance_symbol_validator import BinanceSymbolValidator
    TP_EXTENSION_AVAILABLE = True
except Exception as e:
    log.debug(f"TP Extension unavailable: {e}")
    TP_EXTENSION_AVAILABLE = False

# Import AI post-trade review and consensus improver
try:
    from utils.ai_post_trade_review import review_completed_trade, TradeReviewResult  # type: ignore
    from utils.ai_consensus_improver import analyze_and_apply_improvements  # type: ignore
    from utils.telegram_digest import get_digest, TelegramDigest  # type: ignore
    from utils.telegram_notifier_core import _tg_send
    
    # Wrapper for compatibility (passes parse_mode to Telegram for HTML formatting)
    def send_telegram(message: str, parse_mode: str = "HTML", **kwargs):  # type: ignore
        """Send message via Telegram (sync wrapper for async _tg_send with HTML support)"""
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        # Note: _tg_send doesn't accept parse_mode directly, but Telegram API does via BOT_TOKEN
        # The HTML formatting is handled by Telegram when we send HTML-formatted strings
        loop.run_until_complete(_tg_send(message))
    
    AI_REVIEW_AVAILABLE = True
    log.info("✅ AI Review modules loaded successfully")
except Exception as e:
    log.warning(f"AI review modules unavailable: {e}")
    from typing import Any as _ReviewResult
    TradeReviewResult = _ReviewResult  # type: ignore
    TelegramDigest = _ReviewResult  # type: ignore
    
    async def review_completed_trade(trade_data: Dict[str, Any]) -> Dict[str, Any]:  # type: ignore
        return {}
    async def analyze_and_apply_improvements(review_results: List[Dict[str, Any]]) -> Dict[str, Any]:  # type: ignore
        return {}
    def get_digest():  # type: ignore
        class MockDigest:
            def add_trade_completion(self, *args, **kwargs):
                pass
        return MockDigest()
    def send_telegram(message: str, parse_mode: str = "HTML", **kwargs):  # type: ignore
        pass
    AI_REVIEW_AVAILABLE = False

# ייבוא עדין של לקוח הבורסה
try:
    from utils.binance_client import get_price, get_position_info
except Exception:
    def get_price(symbol: str) -> Optional[float]:
        return None
    def get_position_info(symbol: str) -> Dict[str, Any]:
        # צורת מפתח נפוצה: {"entryPrice": "..., "positionAmt": "...", "updateTime": 123...}
        return {}

# פרמטרים
ENABLED = (os.getenv("FILLS_WATCH_ENABLE", "1").lower() in ("1", "true", "yes", "on"))
INTERVAL = int(os.getenv("FILLS_WATCH_INTERVAL_SEC", "15"))
WATCHLIST = [s.strip().upper() for s in (os.getenv("FILLS_WATCHLIST", os.getenv("WATCHLIST", "")) or "").split(",") if s.strip()]

# Note: BE/Lock functionality moved to trade_manager.py
# fills_watcher focuses on monitoring and metrics only

# זמן כניסה → למדוד time_to_tp1 (בפשטות נאתחל כשיש פוזיציה פעילה)
_entry_ts: Dict[str, float] = {}
_tp1_done: Dict[str, bool] = {}
_last_manage_ts: float = 0.0  # Track last time we called manage_open_trades

# Track active positions for trade completion detection
_active_positions: Dict[str, Dict[str, Any]] = {}  # symbol -> {entry, qty, side, entry_time, ...}
_completed_trades_buffer: List[Dict[str, Any]] = []  # Buffer for batch AI review

# Track TP Extension state
_tp_extension_state: Dict[str, Dict[str, Any]] = {}  # symbol -> {last_tp_hit: int, extended: bool, ...}

# Track Trailing SL state
_trailing_sl_state: Dict[str, Dict[str, Any]] = {}  # symbol -> {peak_price: float, sl_price: float, ...}

def _position_snapshot(symbol: str) -> Tuple[Optional[float], Optional[float]]:
    """
    מחזיר (entry_price, qty_abs) אם יש פוזיציה, אחרת (None, None)
    """
    try:
        info = get_position_info(symbol) or {}
        ep = float(info.get("entryPrice") or 0.0)
        amt = abs(float(info.get("positionAmt") or 0.0))
        if ep > 0 and amt > 0:
            return ep, amt
    except Exception as e:
        log.debug("position_info_failed %s: %s", symbol, e)
    return None, None


def _check_and_extend_tp(symbol: str, current_price: float, entry_price: float, remaining_qty: float) -> None:
    """
    🚀 DYNAMIC TP EXTENSION: Check if price hit TP3/TP4 and generate new TPs.
    
    Args:
        symbol: Trading symbol
        current_price: Current market price
        entry_price: Original entry price
        remaining_qty: Remaining position quantity
    """
    if not TP_EXTENSION_AVAILABLE or remaining_qty <= 0:
        return
    
    # Get position data to determine side
    pos_data = _active_positions.get(symbol)
    if not pos_data:
        return
    
    side = pos_data.get("side", "LONG")
    
    # Get TP data from position metadata (stored when position opened)
    tp_prices = pos_data.get("tp_prices", [])
    if not tp_prices or len(tp_prices) < 3:
        return  # Not a multi-target TP position
    
    # Detect which TP level was just hit
    last_tp_hit = None
    if side == "LONG":
        # For LONG: TP1 < TP2 < TP3 < current_price
        if len(tp_prices) >= 3 and current_price >= tp_prices[2]:
            last_tp_hit = 3
        elif len(tp_prices) >= 4 and current_price >= tp_prices[3]:
            last_tp_hit = 4
    else:  # SHORT
        # For SHORT: TP1 > TP2 > TP3 > current_price
        if len(tp_prices) >= 3 and current_price <= tp_prices[2]:
            last_tp_hit = 3
        elif len(tp_prices) >= 4 and current_price <= tp_prices[3]:
            last_tp_hit = 4
    
    if not last_tp_hit or last_tp_hit < 3:
        return  # Not at TP3/TP4 yet
    
    # Check if we already extended for this TP level
    ext_state = _tp_extension_state.get(symbol, {})
    if ext_state.get("last_tp_hit") == last_tp_hit and ext_state.get("extended"):
        return  # Already extended for this TP level
    
    # Calculate current volatility (ATR)
    try:
        klines = get_klines(symbol, "15m", 24)
        if klines and len(klines) >= 14:
            highs = [float(k[2]) for k in klines]
            lows = [float(k[3]) for k in klines]
            closes = [float(k[4]) for k in klines]
            
            # Simple ATR calculation
            atr_sum = 0.0
            for i in range(1, 14):
                tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
                atr_sum += tr
            atr = atr_sum / 14
            volatility = atr / current_price
        else:
            volatility = 0.02  # Default 2%
    except Exception as e:
        log.debug(f"Failed to calculate ATR for {symbol}: {e}")
        volatility = 0.02
    
    # Get multi-target TP manager
    tp_manager = get_multi_target_tp()
    
    # Build current TP config
    current_config = {
        "targets": [{"price": tp, "exit_percent": 0.33} for tp in tp_prices],
        "trailing_stop": {"trailing_percent": 0.03},
        "risk_reward_ratio": 2.0,
        "side": side
    }
    
    # Generate extended TP levels
    extended_config = tp_manager.extend_tp_levels(
        current_tp_config=current_config,
        last_tp_hit=last_tp_hit,
        current_price=current_price,
        remaining_quantity=remaining_qty,
        volatility=volatility
    )
    
    if not extended_config:
        return
    
    # Place new TP orders
    try:
        validator = BinanceSymbolValidator()
        
        for target in extended_config["targets"]:
            tp_price = target["price"]
            tp_qty = remaining_qty * target["exit_percent"]
            
            # Round to symbol precision
            tp_price_rounded = validator.round_price(symbol, tp_price)
            tp_qty_rounded = validator.round_quantity(symbol, tp_qty)
            
            # Determine order side (opposite of position)
            order_side = "SELL" if side == "LONG" else "BUY"
            
            # Place TP order
            result = futures_create_order(
                symbol=symbol,
                side=order_side,
                type="LIMIT",
                quantity=str(tp_qty_rounded),
                price=str(tp_price_rounded),
                timeInForce="GTC",
                reduceOnly=True,
                positionSide=side
            )
            
            if result.get("ok"):
                log.info(
                    f"✅ TP{target['level']} placed: {symbol} {order_side} {tp_qty_rounded} @ {tp_price_rounded}"
                )
            else:
                log.warning(f"❌ Failed to place TP{target['level']}: {result.get('error')}")
        
        # Update extension state
        _tp_extension_state[symbol] = {
            "last_tp_hit": last_tp_hit,
            "extended": True,
            "new_tps": [t["price"] for t in extended_config["targets"]]
        }
        
        # Send Telegram notification
        try:
            msg = (
                f"🚀 <b>TP Extension Activated!</b>\n\n"
                f"🎯 Symbol: <b>{symbol}</b>\n"
                f"📈 Side: <b>{side}</b>\n"
                f"✅ TP{last_tp_hit} Hit @ <code>{current_price:.4f}</code>\n\n"
                f"🎯 New Targets Generated:\n"
            )
            for target in extended_config["targets"]:
                msg += f"   • TP{target['level']}: <code>{target['price']:.4f}</code> ({target['exit_percent']*100:.0f}%)\n"
            
            send_telegram(msg, parse_mode="HTML")
            log.info(f"✅ TP Extension notification sent for {symbol}")
        except Exception as e:
            log.warning(f"Failed to send TP extension notification: {e}")
    
    except Exception as e:
        log.error(f"❌ Failed to place extended TP orders for {symbol}: {e}", exc_info=True)


def _update_trailing_sl(symbol: str, current_price: float, entry_price: float, remaining_qty: float) -> None:
    """
    🛡️ DYNAMIC TRAILING SL: Update Stop Loss as price moves up, synchronized with TP.
    
    Activates after TP1, moves SL up to lock profits as price climbs.
    Synchronized with TP Extension - when generating new TPs, SL also moves up.
    
    Args:
        symbol: Trading symbol
        current_price: Current market price
        entry_price: Original entry price
        remaining_qty: Remaining position quantity
    """
    if not TP_EXTENSION_AVAILABLE or remaining_qty <= 0:
        return
    
    # Get position data
    pos_data = _active_positions.get(symbol)
    if not pos_data:
        return
    
    side = pos_data.get("side", "LONG")
    original_sl = pos_data.get("sl_price")
    
    if not original_sl:
        return  # No SL to trail
    
    # Get or initialize trailing state
    if symbol not in _trailing_sl_state:
        # Initialize trailing state
        _trailing_sl_state[symbol] = {
            "peak_price": entry_price,
            "current_sl": original_sl,
            "activated": False,
            "last_update_time": time.time()
        }
    
    trail_state = _trailing_sl_state[symbol]
    
    # Check if TP1 was hit (activation trigger)
    tp_prices = pos_data.get("tp_prices", [])
    tp1_hit = False
    if tp_prices and len(tp_prices) >= 1:
        if side == "LONG":
            tp1_hit = current_price >= tp_prices[0]
        else:  # SHORT
            tp1_hit = current_price <= tp_prices[0]
    
    # Activate trailing after TP1
    if not trail_state["activated"] and tp1_hit:
        trail_state["activated"] = True
        trail_state["peak_price"] = current_price
        log.info(f"🛡️ Trailing SL activated for {symbol} @ {current_price:.4f}")
    
    if not trail_state["activated"]:
        return  # Not activated yet
    
    # Update peak price
    peak_updated = False
    if side == "LONG" and current_price > trail_state["peak_price"]:
        trail_state["peak_price"] = current_price
        peak_updated = True
    elif side == "SHORT" and current_price < trail_state["peak_price"]:
        trail_state["peak_price"] = current_price
        peak_updated = True
    
    if not peak_updated:
        return  # Price hasn't improved, no SL update needed
    
    # Calculate trailing distance based on volatility
    try:
        klines = get_klines(symbol, "15m", 24)
        if klines and len(klines) >= 14:
            highs = [float(k[2]) for k in klines]
            lows = [float(k[3]) for k in klines]
            closes = [float(k[4]) for k in klines]
            
            # Calculate ATR
            atr_sum = 0.0
            for i in range(1, 14):
                tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
                atr_sum += tr
            atr = atr_sum / 14
            volatility = atr / current_price
        else:
            volatility = 0.02  # Default 2%
    except Exception as e:
        log.debug(f"Failed to calculate ATR for trailing SL: {e}")
        volatility = 0.02
    
    # Dynamic trailing distance based on volatility and TP level
    # Base distance: 2-5% depending on volatility
    if volatility > 0.10:
        trailing_distance_pct = 0.05  # 5% for high volatility
    elif volatility > 0.05:
        trailing_distance_pct = 0.03  # 3% for medium volatility
    else:
        trailing_distance_pct = 0.02  # 2% for low volatility
    
    # Tighten trailing distance as we reach higher TP levels
    ext_state = _tp_extension_state.get(symbol, {})
    last_tp_hit = ext_state.get("last_tp_hit", 0)
    if last_tp_hit >= 3:
        trailing_distance_pct *= 0.8  # Tighter SL after TP3 (80% of base)
    elif last_tp_hit >= 4:
        trailing_distance_pct *= 0.6  # Even tighter after TP4 (60% of base)
    
    # Calculate new SL price
    if side == "LONG":
        new_sl = trail_state["peak_price"] * (1 - trailing_distance_pct)
        # Only move SL up, never down
        if new_sl <= trail_state["current_sl"]:
            return
    else:  # SHORT
        new_sl = trail_state["peak_price"] * (1 + trailing_distance_pct)
        # Only move SL down (up in price), never up (down in price)
        if new_sl >= trail_state["current_sl"]:
            return
    
    # Throttle updates (minimum 30 seconds between SL updates)
    if time.time() - trail_state["last_update_time"] < 30:
        return
    
    # Round to symbol precision
    try:
        validator = BinanceSymbolValidator()
        new_sl_rounded = validator.round_price(symbol, new_sl)
    except Exception:
        new_sl_rounded = round(new_sl, 4)
    
    # Cancel existing SL order and place new one
    try:
        # Cancel all existing stop orders for this symbol
        from utils.binance_client import futures_cancel_all_orders
        futures_cancel_all_orders(symbol=symbol)
        
        # Place new SL order
        sl_side = "SELL" if side == "LONG" else "BUY"
        result = futures_create_order(
            symbol=symbol,
            side=sl_side,
            type="STOP_MARKET",
            quantity=str(remaining_qty),
            stopPrice=str(new_sl_rounded),
            reduceOnly=True,
            positionSide=side
        )
        
        if result.get("ok"):
            old_sl = trail_state["current_sl"]
            trail_state["current_sl"] = new_sl_rounded
            trail_state["last_update_time"] = time.time()
            
            # Calculate profit locked
            if side == "LONG":
                profit_locked_pct = ((new_sl_rounded - entry_price) / entry_price) * 100
            else:
                profit_locked_pct = ((entry_price - new_sl_rounded) / entry_price) * 100
            
            log.info(
                f"🛡️ Trailing SL updated: {symbol} {old_sl:.4f} → {new_sl_rounded:.4f} "
                f"(Peak: {trail_state['peak_price']:.4f}, Locked: +{profit_locked_pct:.2f}%)"
            )
            
            # Send Telegram notification (throttled)
            try:
                msg = (
                    f"🛡️ <b>Trailing SL Updated!</b>\n\n"
                    f"🎯 Symbol: <b>{symbol}</b>\n"
                    f"📈 Side: <b>{side}</b>\n"
                    f"📊 Peak: <code>{trail_state['peak_price']:.4f}</code>\n"
                    f"🛡️ New SL: <code>{new_sl_rounded:.4f}</code>\n"
                    f"💰 Profit Locked: <code>+{profit_locked_pct:.2f}%</code>\n"
                    f"📏 Trailing: <code>{trailing_distance_pct*100:.1f}%</code> from peak"
                )
                send_telegram(msg, parse_mode="HTML")
                log.info(f"✅ Trailing SL notification sent for {symbol}")
            except Exception as e:
                log.debug(f"Failed to send trailing SL notification: {e}")
        else:
            log.warning(f"❌ Failed to update trailing SL: {result.get('error')}")
    
    except Exception as e:
        log.error(f"❌ Failed to update trailing SL for {symbol}: {e}", exc_info=True)


def _get_trade_params_from_db(symbol: str) -> Dict[str, Any]:
    """
    💾 Retrieve original TP/SL/entry parameters from database for recently opened trade.
    
    This prevents the 0.0 TP/SL calculation issue by reading stored values.
    
    Returns:
        dict: {"tp_price": float|None, "sl_price": float|None, "entry_price": float|None, "leverage": int|None}
    """
    try:
        import psycopg2
        
        DATABASE_URL = os.getenv("DATABASE_URL")
        if not DATABASE_URL:
            log.debug(f"[_get_trade_params_from_db] DATABASE_URL not configured")
            return {}
        
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        
        # Get most recent open trade for this symbol
        cursor.execute("""
            SELECT tp, sl, entry, leverage
            FROM trades_log
            WHERE symbol = %s 
              AND status = 'OPEN'
            ORDER BY opened_at DESC
            LIMIT 1
        """, (symbol,))
        
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        
        if row:
            tp, sl, entry, leverage = row
            log.info(f"💾 [_get_trade_params_from_db] {symbol}: TP={tp}, SL={sl}, Entry={entry}, Leverage={leverage}")
            return {
                "tp_price": float(tp) if tp else None,
                "sl_price": float(sl) if sl else None,
                "entry_price": float(entry) if entry else None,
                "leverage": int(leverage) if leverage else None
            }
        else:
            log.debug(f"[_get_trade_params_from_db] No open trade found for {symbol}")
            return {}
            
    except Exception as e:
        log.error(f"[_get_trade_params_from_db] Failed to retrieve from DB: {e}", exc_info=True)
        return {}


def _tick_symbol(symbol: str):
    # בדיקת פוזיציה
    ep, qty = _position_snapshot(symbol)
    now = time.time()

    if ep and qty and symbol not in _entry_ts:
        _entry_ts[symbol] = now
        _tp1_done[symbol] = False
        
        # Track new position
        # 💎 CRITICAL: Determine side from positionAmt sign, NOT from price comparison!
        # Price comparison is unreliable (e.g., SHORT at 100 with price=101 looks like LONG)
        try:
            pos_info = get_position_info(symbol) or {}
            position_amt = float(pos_info.get("positionAmt") or 0.0)
            
            # ✅ CORRECT: Use sign of positionAmt
            # positionAmt > 0 = LONG
            # positionAmt < 0 = SHORT
            if position_amt > 0:
                side = "LONG"
            elif position_amt < 0:
                side = "SHORT"
            else:
                # Fallback if positionAmt is 0 (shouldn't happen, but be safe)
                log.warning(f"⚠️ positionAmt is 0 for {symbol}, using price comparison fallback")
                current_price = float(get_price(symbol) or ep)
                side = "LONG" if current_price >= ep else "SHORT"
            
            # 💎 Extract ACTUAL leverage from position info (Binance API)
            # This is critical for accurate ROI calculation!
            position_leverage = int(pos_info.get("leverage") or 0) if pos_info.get("leverage") else None
            
        except Exception as e:
            log.warning(f"⚠️ Failed to get position info for {symbol}: {e}, using price comparison fallback")
            current_price = float(get_price(symbol) or ep)
            side = "LONG" if current_price >= ep else "SHORT"
            position_leverage = None
        
        # 💾 Retrieve original TP/SL/entry from database
        db_params = _get_trade_params_from_db(symbol)
        
        # Use DB values if available, otherwise use defaults
        tp_price_from_db = db_params.get("tp_price")
        sl_price_from_db = db_params.get("sl_price")
        leverage_from_db = db_params.get("leverage")
        
        # Prefer leverage from DB if position_leverage is None
        final_leverage = position_leverage if position_leverage is not None else leverage_from_db
        
        _active_positions[symbol] = {
            "entry_price": ep,
            "quantity": qty,  # Absolute value
            "side": side,     # From positionAmt sign
            "entry_time": now,
            "sl_price": sl_price_from_db,  # 💾 From DB instead of None
            "tp_prices": [tp_price_from_db] if tp_price_from_db else [],  # 💾 From DB instead of []
            "regime": "UNKNOWN",
            "leverage": final_leverage  # 💾 Prefer DB, fallback to Binance
        }
        
        log.info(f"💾 Position tracked for {symbol}: TP={tp_price_from_db}, SL={sl_price_from_db}, Leverage={final_leverage}")
        
        # NOTE: Universal SL/TP protection is handled by FillsWatcherThread (_watch_fills_once)
        # No need to duplicate logic here - the dedicated thread will detect fills and attach protection
        
        # 🔔 IMMEDIATE Telegram Notification: Trade Opened (with FULL 5 AI Brains consensus + predictions!)
        try:
            # Try to get consensus data from Redis (stored by symbol)
            consensus_data = None
            try:
                from utils.redis_client import redis_client as RED
                import json
                if RED:
                    consensus_key = f"consensus:{symbol}"
                    consensus_json = RED.get(consensus_key)
                    if consensus_json:
                        if isinstance(consensus_json, bytes):
                            consensus_json = consensus_json.decode('utf-8')
                        consensus_data = json.loads(consensus_json)
                        log.info(f"✅ Consensus loaded from Redis for {symbol}")
            except Exception as e:
                log.debug(f"Failed to load consensus from Redis: {e}")
            
            # Build professional notification with all details
            msg_lines = [
                f"╔═══════════════════════════╗",
                f"║   🚀 <b>טרייד נפתח!</b> 🚀   ║",
                f"╚═══════════════════════════╝",
                f"",
                f"📊 <b>{symbol}</b> | {'📈 LONG' if side == 'LONG' else '📉 SHORT'}",
                f"━━━━━━━━━━━━━━━━━━━━━━━━",
                f"",
                f"💎 <b>פרטי הפוזיציה</b>",
                f"  💵 Entry: <code>{ep:.6f}</code> USDT",
                f"  📦 Quantity: <code>{qty:.4f}</code>",
            ]
            
            # Add SL/TP if available (from DB or calculation)
            if sl_price_from_db and sl_price_from_db > 0:
                sl_pct = abs((sl_price_from_db - ep) / ep * 100)
                msg_lines.append(f"  🛡️ Stop Loss: <code>{sl_price_from_db:.6f}</code> (-{sl_pct:.2f}%)")
            else:
                msg_lines.append(f"  🛡️ Stop Loss: <code>Not set</code> ⚠️")
            
            if tp_price_from_db and tp_price_from_db > 0:
                tp_pct = abs((tp_price_from_db - ep) / ep * 100)
                msg_lines.append(f"  🎯 Take Profit: <code>{tp_price_from_db:.6f}</code> (+{tp_pct:.2f}%)")
            else:
                msg_lines.append(f"  🎯 Take Profit: <code>Not set</code> ⚠️")
            
            # Add leverage if available
            if position_leverage:
                msg_lines.append(f"  ⚡ Leverage: <code>{position_leverage}x</code>")
                position_value = qty * ep
                investment = position_value / position_leverage
                msg_lines.append(f"  💰 Investment: <code>${investment:.2f}</code>")
            
            msg_lines.append(f"  ⏰ {time.strftime('%H:%M:%S', time.localtime(now))}")
            
            # 🧠 Add 5 AI Brains consensus if available
            if consensus_data and isinstance(consensus_data, dict):
                final_vote = consensus_data.get("final_vote", "")
                final_score = consensus_data.get("final_score", 0.0)
                approve_count = consensus_data.get("approve_count", 0)
                brain_votes = consensus_data.get("brain_votes", [])
                
                # Expected profit & duration
                expected_profit_usd = consensus_data.get("expected_profit_usd", 0)
                expected_profit_pct = consensus_data.get("expected_profit_pct", 0)
                expected_duration_hours = consensus_data.get("expected_duration_hours", 0)
                
                msg_lines.extend([
                    f"",
                    f"━━━━━━━━━━━━━━━━━━━━━━━━",
                    f"🧠 <b>קונצנזוס 5 המוחות</b>",
                    f"━━━━━━━━━━━━━━━━━━━━━━━━",
                    f"",
                    f"🗳️ <b>החלטה:</b> {final_vote} ({approve_count}/5 אישרו)",
                    f"⭐ <b>ציון ממוצע:</b> <code>{final_score:.1f}/10</code>",
                ])
                
                # Add predictions if available
                if expected_profit_usd > 0 or expected_profit_pct > 0:
                    msg_lines.extend([
                        f"",
                        f"📈 <b>צפי רווח:</b> <code>+${expected_profit_usd:.2f}</code> ({expected_profit_pct:+.1f}%)",
                    ])
                
                if expected_duration_hours > 0:
                    if expected_duration_hours < 1:
                        duration_str = f"{int(expected_duration_hours * 60)} דקות"
                    elif expected_duration_hours < 24:
                        duration_str = f"{expected_duration_hours:.1f} שעות"
                    else:
                        duration_str = f"{expected_duration_hours / 24:.1f} ימים"
                    msg_lines.append(f"⏱️ <b>צפי זמן:</b> <code>{duration_str}</code>")
                
                if brain_votes:
                    msg_lines.extend([
                        f"",
                        f"<b>פירוט המוחות:</b>",
                    ])
                    
                    # Map brain names to Hebrew + emoji
                    brain_names = {
                        "gpt-5": "🧠 GPT-5 (מנצח)",
                        "gemini": "💎 Gemini 2 Pro",
                        "deepseek": "🔍 DeepSeek",
                        "grok": "⚡ Grok (X.AI)",
                        "claude": "🎓 Claude Sonnet 4.5"
                    }
                    
                    for vote in brain_votes[:5]:
                        brain_key = vote.get("brain", "").lower().replace(" ", "-")
                        brain_display = brain_names.get(brain_key, vote.get("brain", "Unknown"))
                        vote_str = vote.get("vote", "")
                        score = vote.get("score", 0.0)
                        reasoning = vote.get("reasoning", "")[:80]  # More characters
                        
                        emoji = "✅" if vote_str == "APPROVE" else "❌"
                        msg_lines.append(f"{emoji} <b>{brain_display}</b>")
                        msg_lines.append(f"   ציון: <code>{score:.1f}/10</code>")
                        msg_lines.append(f"   {reasoning}...")
                        msg_lines.append("")
            
            msg = "\n".join(msg_lines)
            send_telegram(msg, parse_mode="HTML")
            log.info(f"✅ Telegram sent: Trade opened {symbol} (with FULL AI consensus + predictions)")
        except Exception as e:
            log.error(f"❌ Failed to send trade open notification: {e}", exc_info=True)

    if not (ep and qty):
        # אין פוזיציה → איפוס + detect trade completion
        if symbol in _active_positions:
            # Position closed - trigger AI review
            _on_trade_completion(symbol, now)
        
        _entry_ts.pop(symbol, None)
        _tp1_done.pop(symbol, None)
        _active_positions.pop(symbol, None)
        return

    # חישוב RR ועידכון Gauge
    try:
        current = float(get_price(symbol) or 0.0)
        if current > 0:
            # אין לנו SL/TP כאן; אם יש לך חנות תכניות – אפשר לשאוב ממנה. נשתמש בקירובים:
            sl = ep * 0.985  # 1.5% SL דיפולטי רזה
            tp1 = ep * 1.018  # 1.8% TP1 דיפולטי רזה
            rr = rr_now("BUY" if current >= ep else "SELL", entry=ep, sl=sl, tp=tp1, current=current)
            if rr is not None:
                set_rr(symbol, rr)

            # TP1?
            if not _tp1_done.get(symbol) and ((current >= tp1 and current >= ep) or (current <= tp1 and current <= ep)):
                _tp1_done[symbol] = True
                inc_fill(symbol, "tp1")
                if symbol in _entry_ts:
                    observe_ttp1(now - _entry_ts[symbol])
                
                # 🔔 IMMEDIATE Telegram: TP1 Hit
                try:
                    pnl_pct = ((current - ep) / ep * 100) if current >= ep else ((ep - current) / ep * 100)
                    msg = (
                        f"🎯 <b>TP1 Hit!</b>\n\n"
                        f"🎯 Symbol: <b>{symbol}</b>\n"
                        f"💰 Price: <code>{current:.4f}</code>\n"
                        f"📊 PnL: <code>{pnl_pct:+.2f}%</code>\n"
                        f"⏱️ Time to TP1: <code>{int(now - _entry_ts[symbol])}s</code>"
                    )
                    send_telegram(msg, parse_mode="HTML")
                    log.info(f"✅ Telegram sent: TP1 hit {symbol}")
                except Exception as e:
                    log.warning(f"Failed to send TP1 Telegram: {e}")
            
            # 🚀 TP3/TP4 Extension Detection
            try:
                _check_and_extend_tp(symbol, current, ep, qty)
            except Exception as e:
                log.debug(f"TP extension check failed for {symbol}: {e}")
            
            # 🛡️ Trailing SL Update (synchronized with TP)
            try:
                _update_trailing_sl(symbol, current, ep, qty)
            except Exception as e:
                log.debug(f"Trailing SL update failed for {symbol}: {e}")

    except Exception as e:
        log.debug("tick_symbol_failed %s: %s", symbol, e)


def _on_trade_completion(symbol: str, exit_time: float):
    """Handle trade completion - send professional notification + AI review"""
    try:
        pos_data = _active_positions.get(symbol)
        if not pos_data:
            return
        
        exit_price = float(get_price(symbol) or pos_data["entry_price"])
        entry_price = pos_data["entry_price"]
        side = pos_data["side"]
        quantity = pos_data["quantity"]
        
        # 💎 Get ACTUAL leverage from position data
        # If unknown, assume 1x (no leverage) to be conservative
        leverage = pos_data.get("leverage")
        if leverage is None or leverage == 0:
            log.warning(f"⚠️ Leverage unknown for {symbol} - assuming 1x (no leverage) for ROI calculation")
            leverage = 1  # Conservative fallback - NO leverage assumed
        
        # 💎 CORRECT PNL Calculation
        # PNL in USDT (actual profit/loss)
        if side == "LONG":
            pnl_usd = quantity * (exit_price - entry_price)
        else:
            pnl_usd = quantity * (entry_price - exit_price)
        
        # 💎 CORRECT ROI Calculation - on ACTUAL INVESTMENT (not on price movement!)
        # Investment = (position_value / leverage) = (quantity * entry_price) / leverage
        # With 1x leverage, investment = full position value
        # With 10x leverage, investment = 10% of position value
        actual_investment = (quantity * entry_price) / leverage
        
        # ROI = (PNL / Investment) * 100
        # This is the REAL return on YOUR money, not on the leveraged position!
        pnl_pct = (pnl_usd / actual_investment) * 100 if actual_investment > 0 else 0.0
        
        # Also calculate price movement % (for reference)
        price_movement_pct = ((exit_price - entry_price) / entry_price) * 100 if side == "LONG" else ((entry_price - exit_price) / entry_price) * 100
        duration_min = int((exit_time - pos_data['entry_time']) / 60)
        duration_hours = duration_min // 60
        duration_rem_min = duration_min % 60
        
        trade_data = {
            "trade_id": f"{symbol}_{int(exit_time)}",
            "symbol": symbol,
            "side": side,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "entry_time": pos_data["entry_time"],
            "exit_time": exit_time,
            "pnl_usd": pnl_usd,
            "pnl_pct": pnl_pct,
            "quantity": pos_data["quantity"],
            "leverage": pos_data.get("leverage", 4),
            "exit_reason": "MANUAL_CLOSE",
            "sl_price": pos_data.get("sl_price"),
            "tp_prices": pos_data.get("tp_prices", []),
            "regime": pos_data.get("regime", "UNKNOWN"),
            "strategy": pos_data.get("strategy", "Mean-Reversion")
        }
        
        # 📊 Feed to Order Quality Monitor for tracking
        try:
            from utils.order_quality_monitor import record_order
            from datetime import datetime
            
            # Calculate slippage if we have requested price
            slippage_pct = abs(exit_price - entry_price) / entry_price if entry_price > 0 else 0.0
            
            record_order(
                symbol=symbol,
                order_id=trade_data["trade_id"],
                side="SELL" if side == "LONG" else "BUY",  # Exit order side
                order_type="MARKET",  # Most closes are market orders
                requested_price=entry_price,  # Entry was the target
                filled_price=exit_price,  # Exit was the fill
                requested_qty=quantity,
                filled_qty=quantity,  # Assume full fill on close
                status="FILLED",
                placed_at=datetime.fromtimestamp(pos_data["entry_time"]),
                filled_at=datetime.fromtimestamp(exit_time)
            )
            log.debug(f"📊 Recorded order quality for {symbol}")
        except Exception as e:
            log.debug(f"Failed to record order quality: {e}")
        
        # Add to digest for batch summary
        digest = get_digest()
        digest.add_trade_completion(
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            exit_price=exit_price,
            entry_time=pos_data["entry_time"],
            exit_time=exit_time,
            pnl_usd=pnl_usd,
            pnl_pct=pnl_pct,
            quantity=pos_data["quantity"],
            leverage=trade_data["leverage"],
            exit_reason="MANUAL_CLOSE",
            sl_price=pos_data.get("sl_price"),
            tp_prices=pos_data.get("tp_prices", []),
            regime=pos_data.get("regime", "UNKNOWN")
        )
        
        # Add to buffer for batch AI review
        _completed_trades_buffer.append(trade_data)
        
        # 🎨 Send concise close notification via telegram_notifier
        try:
            from utils.telegram_notifier import send_trade_closed
            import asyncio
            
            # Build close_info with all required fields
            close_info = {
                "symbol": symbol,  # Use function parameter, not pos_data (symbol missing there)
                "pnl_usd": pnl_usd,
                "pnl_pct": pnl_pct,
                "duration_sec": int(exit_time - pos_data.get('entry_time', exit_time)),
                "exit_reason": trade_data.get("exit_reason", "MANUAL"),
                "exit_price": exit_price,
                "avg_exit": exit_price,
                "plan": {
                    "symbol": symbol,
                    "side": side,
                    "entry_price": entry_price,
                    "price": entry_price,
                    "trade_kind": trade_data.get("strategy", "Futures"),
                    "mode": trade_data.get("strategy", "Futures"),
                },
                "leverage": leverage,
                "quantity": quantity,
            }
            
            # Call async send_trade_closed synchronously (blocking) to ensure completion
            try:
                # Try to get existing loop
                try:
                    loop = asyncio.get_running_loop()
                    # If loop is running, schedule in thread-safe way
                    future = asyncio.run_coroutine_threadsafe(send_trade_closed(close_info), loop)
                    # Wait briefly for completion (non-blocking for main thread)
                    future.result(timeout=2.0)
                except RuntimeError:
                    # No running loop, create new one and run synchronously
                    asyncio.run(send_trade_closed(close_info))
            except Exception as async_err:
                log.debug(f"send_trade_closed failed: {async_err}")
        except Exception as notif_err:
            log.warning(f"Failed to send close notification: {notif_err}")
        
        # Legacy detailed message (backup)
        try:
            # Determine outcome
            is_win = pnl_pct > 0
            is_breakeven = abs(pnl_pct) < 0.1
            
            if is_breakeven:
                header_emoji = "⚖️"
                header_text = "TRADE CLOSED - BREAKEVEN"
            elif is_win:
                header_emoji = "🟢"
                header_text = "TRADE CLOSED - WIN"
            else:
                header_emoji = "🔴"
                header_text = "TRADE CLOSED - LOSS"
            
            # Format duration
            if duration_hours > 0:
                duration_str = f"{duration_hours}h {duration_rem_min}min"
            else:
                duration_str = f"{duration_min}min"
            
            # Format prices with thousands separator
            entry_str = f"{entry_price:,.2f}" if entry_price >= 100 else f"{entry_price:.4f}"
            exit_str = f"{exit_price:,.2f}" if exit_price >= 100 else f"{exit_price:.4f}"
            
            # Side emoji
            side_emoji = "📈" if side == "LONG" else "📉"
            
            # Skip legacy detailed message - using concise one instead
            msg_disabled = (
                f"╔═══════════════════════════╗\n"
                f"║  {header_emoji} <b>{header_text}</b> {header_emoji}  ║\n"
                f"║   <b>{pnl_usd:+.2f}$ ({pnl_pct:+.2f}% ROI)</b>        ║\n"
                f"╚═══════════════════════════╝\n\n"
                f"📊 <b>{symbol}</b> | {side_emoji} {side} | ⚡ {trade_data['leverage']}x\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📍 <b>Entry & Exit</b>\n"
                f"  💵 In:  <code>{entry_str}</code>\n"
                f"  🏁 Out: <code>{exit_str}</code>\n"
                f"  ⏱ Duration: <code>{duration_str}</code>\n\n"
                f"💰 <b>Performance</b>\n"
                f"  💎 PnL: <code>${pnl_usd:+.2f}</code>\n"
                f"  📈 ROI: <code>{pnl_pct:+.2f}%</code> (on ${actual_investment:.2f} invested)\n"
                f"  📊 Price Δ: <code>{price_movement_pct:+.2f}%</code>\n\n"
                f"🧠 <b>Strategy</b>\n"
                f"  📋 Type: <code>{trade_data['strategy']}</code>\n"
                f"  🛡 Exit: <code>Position Closed</code>\n"
                f"  🌊 Regime: <code>{trade_data['regime']}</code>\n\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🤖 <i>AI Review in progress...</i>"
            )
            send_telegram(msg_disabled, parse_mode="HTML")
            log.info(f"✅ Professional trade close notification sent: {symbol} PnL={pnl_pct:+.2f}%")
        except Exception as e:
            log.warning(f"Failed to send trade close Telegram: {e}")
        
        # 🧠 TRIGGER AI REVIEW (Async in background)
        if AI_REVIEW_AVAILABLE:
            try:
                log.info(f"🧠 Triggering AI Review for {symbol}...")
                
                async def run_ai_review():
                    try:
                        # Get review from all 5 AI brains
                        review_result = await review_completed_trade(trade_data)
                        
                        if review_result and review_result.get("consensus_score"):
                            consensus = review_result.get("consensus_score", 0)
                            suggestions = review_result.get("top_suggestions", [])
                            
                            # Send AI Review summary to Telegram
                            review_msg = (
                                f"🧠 <b>AI REVIEW COMPLETE</b>\n\n"
                                f"📊 Symbol: <b>{symbol}</b>\n"
                                f"⭐ Consensus Score: <code>{consensus:.1f}/100</code>\n\n"
                                f"📝 <b>Top Suggestions:</b>\n"
                            )
                            
                            for i, suggestion in enumerate(suggestions[:3], 1):
                                review_msg += f"  {i}. {suggestion}\n"
                            
                            review_msg += f"\n🤖 <i>Analyzing for auto-improvements...</i>"
                            send_telegram(review_msg, parse_mode="HTML")
                            
                            # Trigger Auto-Improvement System
                            improvement_result = await analyze_and_apply_improvements([review_result])
                            
                            if improvement_result and improvement_result.get("applied"):
                                improvements = improvement_result.get("improvements", [])
                                improv_msg = (
                                    f"✅ <b>AUTO-IMPROVEMENT APPLIED</b>\n\n"
                                    f"📊 {symbol} - {len(improvements)} change(s)\n"
                                    f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                                )
                                
                                for imp in improvements[:5]:
                                    param = imp.get("parameter", "Unknown")
                                    old_val = imp.get("old_value", "")
                                    new_val = imp.get("new_value", "")
                                    improv_msg += f"🔧 {param}: {old_val} → {new_val}\n"
                                
                                improv_msg += (
                                    f"\n🧠 Consensus: {improvement_result.get('consensus_pct', 0)}%\n"
                                    f"💾 Committed to GitHub ✅\n"
                                    f"🎯 Active from next trade"
                                )
                                send_telegram(improv_msg, parse_mode="HTML")
                                log.info(f"✅ Auto-improvements applied for {symbol}")
                        
                    except Exception as e:
                        log.error(f"AI Review failed for {symbol}: {e}")
                
                # Run async review in background
                import asyncio as async_lib
                loop = async_lib.new_event_loop()
                async_lib.set_event_loop(loop)
                loop.run_until_complete(run_ai_review())
                loop.close()
                
            except Exception as e:
                log.error(f"Failed to trigger AI Review for {symbol}: {e}")
        
        log.info(f"Trade completion processed: {symbol} - PnL: ${pnl_usd:.2f} ({pnl_pct:.2f}%)")
        
    except Exception as e:
        log.error(f"Error processing trade completion for {symbol}: {e}")


class _FillsWatcherThread(threading.Thread):
    """🛡️ Dedicated thread for detecting fills and applying SL/TP protection - runs every 15s"""
    daemon = True
    
    def __init__(self):
        super().__init__()
        self.processed_client_order_ids = set()  # Track processed clientOrderIds to prevent duplicates
        self.last_cleanup = time.time()
    
    def run(self):
        print("🛡️ [FillsWatcherThread] Started - will watch for fills every 15s")
        log.info("[FillsWatcherThread] Started - will watch for fills every 15s")
        
        # Create long-lived asyncio loop for this thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            while True:
                try:
                    loop.run_until_complete(self._watch_fills_once())
                    
                    # Cleanup processed IDs every hour to prevent memory bloat
                    if time.time() - self.last_cleanup > 3600:
                        self.processed_client_order_ids.clear()
                        self.last_cleanup = time.time()
                        log.debug("[FillsWatcherThread] Cleared processed clientOrderIds cache")
                        
                except Exception as e:
                    print(f"❌ [FillsWatcherThread] watch_fills failed: {e}")
                    log.error("[FillsWatcherThread] watch_fills failed: %s", e, exc_info=True)
                
                time.sleep(15)  # Run every 15 seconds
        finally:
            # Clean shutdown
            pending = asyncio.all_tasks(loop)
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.close()
    
    async def _watch_fills_once(self):
        """
        🔍 Check for recent fills across ALL symbols and attach SL/TP protection.
        
        This is the CORE of the Universal SL/TP Protection System!
        """
        try:
            from utils.binance_client import get_recent_fills, futures_get_open_orders
            from utils.universal_sltp_manager import get_order_metadata, attach_sltp_protection, delete_order_metadata
            from utils.redis_client import redis_client
            
            # Get list of symbols with metadata (these are orders we've placed that need protection)
            symbols_with_metadata = set()
            
            try:
                if redis_client:
                    # Scan Redis for all metadata keys (sltp:meta:*)
                    cursor = 0
                    while True:
                        cursor, keys = redis_client.scan(cursor, match="sltp:meta:*", count=100)
                        for key in keys:
                            # Extract symbol from metadata
                            try:
                                metadata_json = redis_client.get(key)
                                if metadata_json:
                                    if isinstance(metadata_json, bytes):
                                        metadata_json = metadata_json.decode('utf-8')
                                    import json
                                    metadata = json.loads(metadata_json)
                                    symbol = metadata.get("symbol")
                                    if symbol:
                                        symbols_with_metadata.add(symbol)
                            except Exception as parse_err:
                                log.debug(f"Failed to parse metadata key {key}: {parse_err}")
                        
                        if cursor == 0:
                            break
            except Exception as redis_err:
                log.debug(f"Redis scan failed: {redis_err}")
            
            # Also get symbols with open orders (backup method)
            try:
                all_open_orders = futures_get_open_orders() or []
                for order in all_open_orders:
                    symbol = order.get("symbol")
                    if symbol:
                        symbols_with_metadata.add(symbol)
            except Exception as orders_err:
                log.debug(f"Failed to get open orders: {orders_err}")
            
            if not symbols_with_metadata:
                log.debug("[FillsWatcherThread] No symbols with pending metadata or open orders")
                return
            
            log.info(f"🔍 [FillsWatcherThread] Checking {len(symbols_with_metadata)} symbols for recent fills...")
            
            fills_checked = 0
            fills_protected = 0
            
            # Check each symbol for recent fills
            for symbol in symbols_with_metadata:
                try:
                    # Get recent fills (last 5 minutes)
                    recent_fills = get_recent_fills(symbol, limit=20, lookback_seconds=300)
                    
                    if not recent_fills:
                        continue
                    
                    fills_checked += len(recent_fills)
                    
                    # Process each fill
                    for fill in recent_fills:
                        client_order_id = fill.get("clientOrderId") or fill.get("origClientOrderId")
                        
                        if not client_order_id:
                            continue
                        
                        # Skip if already processed
                        if client_order_id in self.processed_client_order_ids:
                            continue
                        
                        # Retrieve metadata
                        metadata = get_order_metadata(client_order_id)
                        
                        if not metadata:
                            # No metadata = not our order (or already cleaned up)
                            continue
                        
                        # Found metadata! This fill needs protection
                        trade_type = metadata.get("trade_type", "UNKNOWN")
                        sl_price = metadata.get("sl_price")
                        tp_price = metadata.get("tp_price")
                        fill_side = metadata.get("side")  # LONG/SHORT
                        
                        if not (sl_price and tp_price and fill_side):
                            log.warning(f"⚠️ Incomplete metadata for {client_order_id}: SL={sl_price}, TP={tp_price}, Side={fill_side}")
                            continue
                        
                        log.info(f"🛡️ [{trade_type}] Fill detected: {symbol} | clientOrderId={client_order_id}")
                        log.info(f"📈 Protection: SL={sl_price:.6f}, TP={tp_price:.6f}, Side={fill_side}")
                        
                        # Attach SL/TP protection
                        protection_result = await attach_sltp_protection(
                            symbol=symbol,
                            side=fill_side,
                            sl_price=sl_price,
                            tp_price=tp_price
                        )
                        
                        if protection_result["ok"]:
                            log.info(f"✅ [{trade_type}] SL/TP protection applied: {symbol}")
                            fills_protected += 1
                            
                            # Mark as processed
                            self.processed_client_order_ids.add(client_order_id)
                            
                            # Cleanup metadata (TTL will handle it, but we can clean early)
                            delete_order_metadata(client_order_id)
                        else:
                            errors = protection_result.get("errors", [])
                            log.error(f"❌ [{trade_type}] SL/TP protection FAILED: {symbol} - {errors}")
                        
                except Exception as symbol_err:
                    log.error(f"Failed to process fills for {symbol}: {symbol_err}", exc_info=True)
            
            if fills_protected > 0:
                log.info(f"✅ [FillsWatcherThread] Protected {fills_protected}/{fills_checked} fills across {len(symbols_with_metadata)} symbols")
            else:
                log.debug(f"[FillsWatcherThread] Checked {fills_checked} fills across {len(symbols_with_metadata)} symbols - none needed protection")
                
        except Exception as e:
            log.error(f"[FillsWatcherThread] Critical error in watch_fills: {e}", exc_info=True)


class _TradeManagerThread(threading.Thread):
    """Dedicated thread for dynamic SL/TP/BE/Trailing management - runs every 60s"""
    daemon = True

    def run(self):
        print("🔧 [TradeManagerThread] Started - will manage open trades every 60s")
        log.info("[TradeManagerThread] Started - will manage open trades every 60s")
        
        # 🛡️ FIX: Create long-lived asyncio loop for this thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            while True:
                try:
                    print(f"🔧 [TradeManagerThread] Running manage_open_trades() at {time.strftime('%H:%M:%S')}")
                    loop.run_until_complete(manage_open_trades())
                    print(f"✅ [TradeManagerThread] Completed manage_open_trades() at {time.strftime('%H:%M:%S')}")
                except Exception as e:
                    print(f"❌ [TradeManagerThread] manage_open_trades failed: {e}")
                    log.error("[TradeManagerThread] manage_open_trades failed: %s", e)
                time.sleep(60)
        finally:
            # Clean shutdown: wait for all tasks before closing loop
            pending = asyncio.all_tasks(loop)
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.close()


class _Worker(threading.Thread):
    daemon = True
    def run(self):
        # Start dedicated fills watcher thread (CRITICAL for SL/TP protection!)
        fills_thread = _FillsWatcherThread()
        fills_thread.start()
        print("✅ [fills_watcher] Fills watcher thread started (15s interval)")
        log.info("[fills_watcher] Fills watcher thread started (15s interval)")
        
        # Start dedicated trade manager thread (independent of WATCHLIST)
        mgmt = _TradeManagerThread()
        mgmt.start()
        print("✅ [fills_watcher] Trade manager thread started (60s interval)")
        log.info("[fills_watcher] Trade manager thread started (60s interval)")

        if not WATCHLIST:
            log.info("[fills_watcher] WATCHLIST empty (optional) - TradeManager runs independently on all open positions")
        else:
            log.info("[fills_watcher] Monitoring %d symbols for metrics", len(WATCHLIST))
        
        while True:
            if not ENABLED:
                time.sleep(INTERVAL)
                continue
            for sym in WATCHLIST:
                try:
                    _tick_symbol(sym)
                except Exception as e:
                    log.debug("watcher_error %s: %s", sym, e)
            time.sleep(INTERVAL)


_worker: Optional[_Worker] = None

def start():
    global _worker
    if _worker is None:
        _worker = _Worker()
        _worker.start()
        log.info("[fills_watcher] started (interval=%ss, enabled=%s, watch=%s)", INTERVAL, ENABLED, WATCHLIST)

if __name__ == "__main__":
    print("⚡ [fills_watcher] __main__ entry - starting worker...")
    start()
    print("⚡ [fills_watcher] Worker started successfully")
    # Keep process alive - daemon thread needs main thread running
    while True:
        time.sleep(60)
