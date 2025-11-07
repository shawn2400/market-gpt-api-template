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
    from utils.ai_post_trade_review import review_completed_trade
    from utils.ai_consensus_improver import analyze_and_apply_improvements
    from utils.telegram_digest import get_digest
    from utils.telegram_send import send_telegram
except Exception as e:
    log.warning(f"AI review modules unavailable: {e}")
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


def _tick_symbol(symbol: str):
    # בדיקת פוזיציה
    ep, qty = _position_snapshot(symbol)
    now = time.time()

    if ep and qty and symbol not in _entry_ts:
        _entry_ts[symbol] = now
        _tp1_done[symbol] = False
        
        # Track new position
        current_price = float(get_price(symbol) or ep)
        side = "LONG" if current_price >= ep else "SHORT"
        _active_positions[symbol] = {
            "entry_price": ep,
            "quantity": qty,
            "side": side,
            "entry_time": now,
            "sl_price": None,
            "tp_prices": [],
            "regime": "UNKNOWN"
        }
        
        # 🔔 IMMEDIATE Telegram Notification: Trade Opened
        try:
            msg = (
                f"🚀 <b>טרייד נפתח</b>\n\n"
                f"🎯 Symbol: <b>{symbol}</b>\n"
                f"{'📈 LONG' if side == 'LONG' else '📉 SHORT'}\n"
                f"💵 Entry: <code>{ep:.4f}</code>\n"
                f"📦 Quantity: <code>{qty:.4f}</code>\n"
                f"⏰ {time.strftime('%H:%M:%S', time.localtime(now))}"
            )
            send_telegram(msg, parse_mode="HTML")
            log.info(f"✅ Telegram sent: Trade opened {symbol}")
        except Exception as e:
            log.warning(f"Failed to send Telegram notification: {e}")

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
    """Handle trade completion - send to AI review"""
    try:
        pos_data = _active_positions.get(symbol)
        if not pos_data:
            return
        
        exit_price = float(get_price(symbol) or pos_data["entry_price"])
        entry_price = pos_data["entry_price"]
        side = pos_data["side"]
        
        # Calculate PnL
        if side == "LONG":
            pnl_pct = ((exit_price - entry_price) / entry_price) * 100
        else:
            pnl_pct = ((entry_price - exit_price) / entry_price) * 100
        
        pnl_usd = pnl_pct * 10  # Rough estimate
        
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
            "leverage": 4,  # Default
            "exit_reason": "MANUAL_CLOSE",  # Could be enhanced to detect SL/TP
            "sl_price": pos_data.get("sl_price"),
            "tp_prices": pos_data.get("tp_prices", []),
            "regime": pos_data.get("regime", "UNKNOWN")
        }
        
        # Add to digest for immediate summary
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
            leverage=4,
            exit_reason="MANUAL_CLOSE",
            sl_price=pos_data.get("sl_price"),
            tp_prices=pos_data.get("tp_prices", []),
            regime=pos_data.get("regime", "UNKNOWN")
        )
        
        # Add to buffer for batch AI review
        _completed_trades_buffer.append(trade_data)
        
        # 🔔 IMMEDIATE Telegram: Trade Closed + Trigger AI Review
        try:
            pnl_emoji = "💚" if pnl_pct > 0 else "❤️"
            msg = (
                f"{pnl_emoji} <b>טרייד נסגר</b>\n\n"
                f"🎯 Symbol: <b>{symbol}</b>\n"
                f"{'📈 LONG' if side == 'LONG' else '📉 SHORT'}\n"
                f"💵 Entry: <code>{entry_price:.4f}</code>\n"
                f"🏁 Exit: <code>{exit_price:.4f}</code>\n"
                f"💰 PnL: <code>{pnl_pct:+.2f}% (${pnl_usd:+.2f})</code>\n"
                f"⏰ Duration: <code>{int((exit_time - pos_data['entry_time']) / 60)}min</code>\n"
                f"━━━━━━━━━━━━━━━\n"
                f"🤖 <i>AI Review coming soon...</i>"
            )
            send_telegram(msg, parse_mode="HTML")
            log.info(f"✅ Telegram sent: Trade closed {symbol} PnL={pnl_pct:+.2f}%")
        except Exception as e:
            log.warning(f"Failed to send trade close Telegram: {e}")
        
        log.info(f"Trade completion detected: {symbol} - PnL: ${pnl_usd:.2f} ({pnl_pct:.2f}%)")
        
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
