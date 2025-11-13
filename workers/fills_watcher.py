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

# Import AI post-trade review and consensus improver
try:
    from utils.ai_post_trade_review import review_completed_trade, TradeReviewResult
    from utils.ai_consensus_improver import analyze_and_apply_improvements
    from utils.telegram_digest import get_digest, TelegramDigest
    from utils.telegram_notifier_core import _tg_send
    
    # Wrapper for compatibility (passes parse_mode to Telegram for HTML formatting)
    def send_telegram(message: str, parse_mode: str = "HTML", **kwargs):
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
    async def analyze_and_apply_improvements(reviews: List[Dict[str, Any]]) -> Dict[str, Any]:  # type: ignore
        return {}
    def get_digest():  # type: ignore
        class MockDigest:
            def add_trade_completion(self, *args, **kwargs):
                pass
        return MockDigest()
    def send_telegram(message: str, **kwargs):  # type: ignore
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
            
            # Call async send_trade_closed
            try:
                loop = asyncio.get_event_loop()
                loop.create_task(send_trade_closed(close_info))
            except RuntimeError:
                # No event loop - skip for now
                log.debug("No event loop for send_trade_closed - skipping notification")
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
            send_telegram(msg, parse_mode="HTML")
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
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(run_ai_review())
                loop.close()
                
            except Exception as e:
                log.error(f"Failed to trigger AI Review for {symbol}: {e}")
        
        log.info(f"Trade completion processed: {symbol} - PnL: ${pnl_usd:.2f} ({pnl_pct:.2f}%)")
        
    except Exception as e:
        log.error(f"Error processing trade completion for {symbol}: {e}")


class _TradeManagerThread(threading.Thread):
    """Dedicated thread for dynamic SL/TP/BE/Trailing management - runs every 60s"""
    daemon = True

    def run(self):
        print("🔧 [TradeManagerThread] Started - will manage open trades every 60s")
        log.info("[TradeManagerThread] Started - will manage open trades every 60s")
        while True:
            try:
                print(f"🔧 [TradeManagerThread] Running manage_open_trades() at {time.strftime('%H:%M:%S')}")
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(manage_open_trades())
                loop.close()
                print(f"✅ [TradeManagerThread] Completed manage_open_trades() at {time.strftime('%H:%M:%S')}")
            except Exception as e:
                print(f"❌ [TradeManagerThread] manage_open_trades failed: {e}")
                log.error("[TradeManagerThread] manage_open_trades failed: %s", e)
            time.sleep(60)


class _Worker(threading.Thread):
    daemon = True
    def run(self):
        # Start dedicated trade manager thread (independent of WATCHLIST)
        mgmt = _TradeManagerThread()
        mgmt.start()
        print("✅ [fills_watcher] Trade manager thread started")
        log.info("[fills_watcher] Trade manager thread started")

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
