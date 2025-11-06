#!/usr/bin/env python3
"""
MetaBrain v9.0 Scanner - 100% Autonomous Dynamic AI Trading
=============================================================
Scans 531 Binance Futures symbols and generates trade proposals using:
- 2 AI Scouts (Market Scanner + Technical Analyst)
- 5 AI Brains (GPT-5, Gemini, DeepSeek, Grok, Claude) for consensus voting
- 3 System Modules (Market Intelligence, Budget Manager, Strategy Orchestrator)

Features:
✅ 100% dynamic - AI decides EVERYTHING (LONG/SHORT/GRID/SPOT)
✅ Scans in ALL market conditions (strong/weak/neutral)
✅ Adapts to wallet size (small/large)
✅ Quality thresholds are safety nets, NOT blockers
✅ Reports 70% Hebrew, 30% English
"""

import os
import sys
import time
import asyncio
import logging
from typing import Dict, Any, List, Optional

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.metabrain_orchestrator import get_metabrain_orchestrator
from utils.watchlist_utils import load_watchlist
from utils.telegram_digest import send_alert_immediate

logger = logging.getLogger("metabrain_scanner")
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Configuration
SCAN_INTERVAL_SEC = int(os.getenv("METABRAIN_SCAN_INTERVAL", "180"))  # 3 minutes default
SYMBOLS_PER_CYCLE = int(os.getenv("METABRAIN_SYMBOLS_PER_CYCLE", "10"))
MIN_QUALITY_THRESHOLD = float(os.getenv("METABRAIN_MIN_QUALITY", "5.5"))  # Flexible safety net
TELEGRAM_ENABLED = os.getenv("TELEGRAM_SEND_ENABLE", "1").lower() in ("1", "true", "yes")


class MetaBrainScanner:
    """
    MetaBrain v9.0 Scanner - Fully autonomous AI trading system.
    
    Workflow:
    1. Load watchlist (531 symbols)
    2. Rotate through symbols (10 per cycle)
    3. For each symbol:
       a. 2 Scouts analyze (Market Scanner + Technical Analyst)
       b. 5 AI Brains vote (≥3 APPROVE = execute)
       c. Budget Manager calculates position
       d. Generate trade proposal
    4. Send to Telegram with full 10-module report
    """
    
    def __init__(self):
        self.logger = logger
        self.orchestrator = get_metabrain_orchestrator()
        self.symbol_index = 0
        self.cycle_count = 0
        
        self.logger.info("🚀 MetaBrain v9.0 Scanner initialized")
        self.logger.info(f"⚙️ Config: {SYMBOLS_PER_CYCLE} symbols/cycle, {SCAN_INTERVAL_SEC}s interval")
    
    async def get_market_data(self, symbol: str) -> Dict[str, Any]:
        """
        Fetch market data for symbol.
        
        TODO: Replace with actual Binance API call or context endpoint
        For now, returns mock data to test the workflow.
        """
        # This is a simplified mock - replace with real data
        return {
            "symbol": symbol,
            "price": 43250.0,
            "volume_24h": 1500000000,
            "volume_avg_7d": 1200000000,
            "price_change_24h_pct": 2.5,
            "liquidity_score": 8.5,
            "atr": 1000,
            "atr_pct": 2.3,
            "rsi": 58,
            "macd_signal": "bullish",
            "ema_20": 43100,
            "ema_50": 42800,
            "support_level": 42900,
            "resistance_level": 43600,
            "regime": "CHOPPY",
            "bb_upper": 43800,
            "bb_lower": 42700
        }
    
    async def get_wallet_state(self) -> Dict[str, Any]:
        """
        Get wallet state from Binance.
        
        TODO: Replace with actual Binance Futures API call
        For now, returns mock data.
        """
        # Mock wallet - replace with real Binance call
        return {
            "total_balance": 1000.0,
            "available_balance": 850.0,
            "locked_in_trades": 150.0,
            "open_positions": 2
        }
    
    async def scan_symbol(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Scan a single symbol using MetaBrain orchestrator.
        
        Args:
            symbol: Trading symbol (e.g., "BTCUSDT")
        
        Returns:
            Trade proposal dict if approved, None if rejected
        """
        try:
            self.logger.info(f"🔍 Scanning {symbol}...")
            
            # Get market data
            market_data = await self.get_market_data(symbol)
            
            # Get wallet state
            wallet_state = await self.get_wallet_state()
            
            # Run MetaBrain orchestration
            result = await self.orchestrator.analyze_and_propose(
                symbol=symbol,
                market_data=market_data,
                wallet_state=wallet_state,
                multi_tf_data=None  # TODO: Add multi-TF analysis
            )
            
            decision = result.get("decision")
            
            if decision == "APPROVE":
                self.logger.info(f"✅ {symbol}: APPROVED by MetaBrain")
                return result
            else:
                reason = result.get("reason", "Unknown")
                self.logger.info(f"❌ {symbol}: REJECTED - {reason}")
                return None
        
        except Exception as e:
            self.logger.error(f"Failed to scan {symbol}: {e}", exc_info=True)
            return None
    
    async def send_telegram_report(self, proposal: Dict[str, Any]):
        """
        Send trade proposal to Telegram with full 10-module report.
        
        Format: 70% Hebrew, 30% English
        """
        if not TELEGRAM_ENABLED:
            return
        
        try:
            symbol = proposal.get("symbol", "UNKNOWN")
            strategy = proposal.get("strategy", "UNKNOWN")
            side = proposal.get("side", "UNKNOWN")
            
            # Extract scores
            scores = proposal.get("scores", {})
            scouts = scores.get("scouts", {})
            brains = scores.get("brains", {})
            final_score = scores.get("final", 0)
            consensus_pct = scores.get("consensus_pct", 0)
            
            # Extract budget
            budget = proposal.get("budget", {})
            position_size = budget.get("position_size_usdt", 0)
            leverage = budget.get("leverage", 1)
            
            # Extract prices
            entry = proposal.get("entry_price", 0)
            sl = proposal.get("sl_price", 0)
            tp = proposal.get("tp_price", 0)
            rr = proposal.get("risk_reward", 0)
            
            # Build Telegram message
            message = f"""
🎯 <b>הצעת טרייד חדשה - MetaBrain v9.0</b>

💎 <b>{symbol} {strategy}</b> | כניסה: ${entry:,.2f}

📊 <b>ציון כולל: {final_score:.1f}/10</b> ({consensus_pct:.0f}% קונצנזוס)

🧠 <b>ציוני 7 המוחות:</b>

<b>👁️ סוכני הסריקה:</b>
┣━ 🔍 <b>Market Scanner: {scouts.get('market_scanner', 0):.1f}/10</b>
   └─ {proposal.get('scouts_detail', {}).get('market_scanner', {}).get('reasoning', 'N/A')[:80]}
┗━ 📈 <b>Technical Analyst: {scouts.get('technical_analyst', 0):.1f}/10</b>
   └─ {proposal.get('scouts_detail', {}).get('technical_analyst', {}).get('reasoning', 'N/A')[:80]}

<b>🤖 מוחות ההחלטה (5 AI Brains):</b>
""".strip()
            
            # Add brain votes
            consensus_detail = proposal.get("consensus_detail", {})
            brain_votes = consensus_detail.get("brain_votes", [])
            
            for brain in brain_votes:
                vote_emoji = "✅" if brain["vote"] == "APPROVE" else "❌"
                brain_name = brain["brain"]
                brain_score = brain["score"]
                
                # Map brain names to emojis
                brain_emojis = {
                    "GPT-5": "🌟",
                    "Gemini 2 Pro": "💎",
                    "DeepSeek": "🔥",
                    "Grok": "⚡",
                    "Claude Sonnet 3.5": "🎓"
                }
                emoji = brain_emojis.get(brain_name, "🤖")
                
                message += f"\n┣━ {emoji} <b>{brain_name}: {brain_score:.1f}/10</b> {vote_emoji}"
            
            # Add budget & protections
            message += f"""

<b>🔧 פרמטרי טרייד:</b>
┣━ 💰 <b>תקציב:</b> ${position_size:.2f} | <b>מינוף:</b> {leverage}x
┣━ 🎯 <b>כניסה:</b> ${entry:,.2f}
┣━ 🛑 <b>SL:</b> ${sl:,.2f}
┣━ 🎁 <b>TP:</b> ${tp:,.2f}
┗━ 📊 <b>RR:</b> {rr:.2f}:1

💡 <b>סיבה:</b> {budget.get('reason', 'N/A')}

⏰ {time.strftime('%Y-%m-%d %H:%M:%S')}
"""
            
            # Send to Telegram
            await send_alert_immediate(message, parse_mode="HTML")
            self.logger.info(f"📱 Telegram report sent for {symbol}")
        
        except Exception as e:
            self.logger.error(f"Failed to send Telegram report: {e}", exc_info=True)
    
    async def run_cycle(self):
        """
        Run one scanning cycle.
        
        Scans SYMBOLS_PER_CYCLE symbols from the watchlist.
        """
        try:
            # Load watchlist
            watchlist = load_watchlist()
            symbols = list(watchlist.keys()) if isinstance(watchlist, dict) else watchlist
            
            if not symbols:
                self.logger.warning("⚠️ No symbols in watchlist - sleeping")
                return
            
            self.cycle_count += 1
            self.logger.info(f"\n{'='*60}")
            self.logger.info(f"🔄 Cycle {self.cycle_count}: Scanning {len(symbols)} symbols")
            self.logger.info(f"{'='*60}\n")
            
            # Get next batch of symbols
            end_index = self.symbol_index + SYMBOLS_PER_CYCLE
            batch = symbols[self.symbol_index:end_index]
            
            # Wrap around if we reach the end
            if end_index >= len(symbols):
                self.symbol_index = 0
            else:
                self.symbol_index = end_index
            
            self.logger.info(f"📋 Batch ({len(batch)} symbols): {', '.join(batch)}")
            
            # Scan each symbol
            approved_count = 0
            for symbol in batch:
                proposal = await self.scan_symbol(symbol)
                
                if proposal:
                    approved_count += 1
                    await self.send_telegram_report(proposal)
                    
                    # Respect rate limits
                    await asyncio.sleep(2)
            
            self.logger.info(f"\n✅ Cycle {self.cycle_count} complete: {approved_count}/{len(batch)} approved\n")
        
        except Exception as e:
            self.logger.error(f"Cycle failed: {e}", exc_info=True)
    
    async def run_forever(self):
        """
        Run scanner continuously.
        
        Scans symbols every SCAN_INTERVAL_SEC seconds.
        """
        self.logger.info(f"🚀 MetaBrain Scanner starting - interval: {SCAN_INTERVAL_SEC}s")
        
        while True:
            try:
                await self.run_cycle()
                
                self.logger.info(f"⏸️ Sleeping for {SCAN_INTERVAL_SEC}s...\n")
                await asyncio.sleep(SCAN_INTERVAL_SEC)
            
            except KeyboardInterrupt:
                self.logger.info("🛑 Scanner stopped by user")
                break
            except Exception as e:
                self.logger.error(f"Scanner error: {e}", exc_info=True)
                await asyncio.sleep(30)  # Wait 30s on error


async def main():
    """Main entry point."""
    scanner = MetaBrainScanner()
    await scanner.run_forever()


if __name__ == "__main__":
    asyncio.run(main())
