"""
Auto-Optimization Orchestrator - Central Optimization Manager
=============================================================
Runs every 4-6 hours to analyze performance and automatically adjust
all trading parameters, tiers, and blacklists for continuous improvement.

Orchestrates:
1. Symbol Stats Aggregation
2. Auto Parameter Tuning
3. Multi-Level Protection
4. Symbol Tiering
5. Dynamic Blacklist Management
6. Enhanced Reporting

Author: AlgoGPT Team
"""

import logging
import os
import asyncio
from typing import Dict
from datetime import datetime, timedelta

from workers.auto_parameter_tuner import AutoParameterTuner
from workers.multi_level_protector import MultiLevelProtector
from workers.symbol_tiering_engine import SymbolTieringEngine
from workers.blacklist_manager import BlacklistManager
from utils.performance_tracker import get_performance_tracker

LOGGER = logging.getLogger("auto_optimization")


class AutoOptimizationOrchestrator:
    """
    Central orchestrator for all auto-optimization processes.
    
    Runs comprehensive optimization cycle:
    - Analyzes performance metrics
    - Adjusts trading parameters
    - Updates symbol tiers
    - Manages blacklists
    - Activates protections if needed
    - Sends optimization reports
    """
    
    def __init__(self):
        self.logger = LOGGER
        
        # Initialize all subsystems
        self.performance_tracker = get_performance_tracker()
        self.parameter_tuner = AutoParameterTuner()
        self.protector = MultiLevelProtector()
        self.tiering_engine = SymbolTieringEngine()
        self.blacklist_manager = BlacklistManager()
        
        # Configuration
        self.optimization_interval_hours = int(os.getenv("OPTIMIZATION_INTERVAL_HOURS", "4"))
        self.lookback_days = int(os.getenv("OPTIMIZATION_LOOKBACK_DAYS", "7"))
        
        self.last_run: datetime = None
    
    async def run_optimization_cycle(self) -> Dict:
        """
        Execute complete optimization cycle.
        
        Returns:
            Dict with optimization results from all subsystems
        """
        self.logger.info("=" * 60)
        self.logger.info("🚀 AUTO-OPTIMIZATION CYCLE STARTED")
        self.logger.info("=" * 60)
        
        start_time = datetime.utcnow()
        
        results = {
            "cycle_started_at": start_time.isoformat(),
            "lookback_days": self.lookback_days,
            "subsystems": {}
        }
        
        try:
            # Step 1: Aggregate Symbol Statistics
            self.logger.info("📊 Step 1/6: Aggregating symbol statistics...")
            symbol_stats = self.performance_tracker.get_all_symbol_stats(
                days=self.lookback_days,
                min_trades=3
            )
            results["subsystems"]["symbol_stats"] = {
                "total_symbols": len(symbol_stats),
                "symbols_analyzed": list(symbol_stats.keys())
            }
            self.logger.info(f"   ✅ Analyzed {len(symbol_stats)} symbols")
            
            # Step 2: Tune Trading Parameters
            self.logger.info("⚙️ Step 2/6: Tuning trading parameters...")
            tuning_result = self.parameter_tuner.analyze_and_tune(days=self.lookback_days)
            results["subsystems"]["parameter_tuning"] = tuning_result
            
            if tuning_result["action"] == "adjust":
                self.logger.info(f"   ✅ Parameters adjusted ({tuning_result['reason']})")
            else:
                self.logger.info(f"   ✅ Parameters stable ({tuning_result.get('reason', 'optimal')})")
            
            # Step 3: Check and Activate Protections
            self.logger.info("🛡️ Step 3/6: Checking protection levels...")
            protection_result = self.protector.check_and_activate_protections(
                days=self.lookback_days
            )
            results["subsystems"]["protection"] = protection_result
            
            self.logger.info(f"   ✅ Protection level: {protection_result['current_level']}")
            
            # Step 4: Update Symbol Tiers
            self.logger.info("📊 Step 4/6: Updating symbol tiers...")
            tier_assignments = self.tiering_engine.calculate_all_tiers(
                days=self.lookback_days,
                min_trades=3
            )
            
            tier_changes = self.tiering_engine.detect_tier_changes(tier_assignments)
            
            results["subsystems"]["tiering"] = {
                "total_classified": len(tier_assignments),
                "tier_changes": tier_changes,
                "tier_distribution": self._count_tiers(tier_assignments)
            }
            
            self.logger.info(
                f"   ✅ Classified {len(tier_assignments)} symbols, "
                f"{len(tier_changes)} tier changes"
            )
            
            # Step 5: Manage Blacklist
            self.logger.info("🚫 Step 5/6: Managing blacklist...")
            blacklist_result = self.blacklist_manager.auto_manage_blacklist(
                days=self.lookback_days
            )
            results["subsystems"]["blacklist"] = blacklist_result
            
            self.logger.info(
                f"   ✅ Blacklist updated: "
                f"+{len(blacklist_result['newly_blacklisted'])} new, "
                f"{blacklist_result['total_blacklisted']} active"
            )
            
            # Step 6: Generate and Send Report
            self.logger.info("📨 Step 6/6: Sending optimization report...")
            await self._send_optimization_report(results)
            self.logger.info("   ✅ Report sent to Telegram")
            
        except Exception as e:
            self.logger.error(f"❌ Optimization cycle failed: {e}", exc_info=True)
            results["error"] = str(e)
            results["status"] = "failed"
        else:
            results["status"] = "success"
        
        # Record completion
        end_time = datetime.utcnow()
        duration = (end_time - start_time).total_seconds()
        
        results["cycle_completed_at"] = end_time.isoformat()
        results["duration_seconds"] = duration
        
        self.last_run = end_time
        
        self.logger.info("=" * 60)
        self.logger.info(f"✅ AUTO-OPTIMIZATION CYCLE COMPLETED ({duration:.1f}s)")
        self.logger.info("=" * 60)
        
        return results
    
    def _count_tiers(self, tier_assignments: Dict) -> Dict:
        """Count symbols per tier"""
        counts = {"A": 0, "B": 0, "C": 0}
        for info in tier_assignments.values():
            tier = info["tier"]
            counts[tier] = counts.get(tier, 0) + 1
        return counts
    
    async def _send_optimization_report(self, results: Dict):
        """Send comprehensive optimization report to Telegram"""
        try:
            import httpx
            
            BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
            CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
            
            if not BOT_TOKEN or not CHAT_ID:
                self.logger.debug("Telegram not configured - skipping report")
                return
            
            # Build report message
            param_tuning = results["subsystems"].get("parameter_tuning", {})
            protection = results["subsystems"].get("protection", {})
            tiering = results["subsystems"].get("tiering", {})
            blacklist = results["subsystems"].get("blacklist", {})
            
            # Parameter changes
            if param_tuning.get("action") == "adjust":
                new_params = param_tuning.get("new_params", {})
                param_changes = f"""
• Min Quality: {new_params.get('min_quality', 'N/A'):.1f}
• Min RR: {new_params.get('min_rr', 'N/A'):.2f}
• Max Leverage: {new_params.get('max_leverage', 'N/A')}
"""
            else:
                param_changes = "• No changes (optimal performance)"
            
            # Tier changes
            tier_changes = tiering.get("tier_changes", [])
            if tier_changes:
                tier_summary = "\n".join([
                    f"• {c['symbol']}: {c['old_tier']} → {c['new_tier']} ({c['change_type']})"
                    for c in tier_changes[:5]  # Show top 5
                ])
                if len(tier_changes) > 5:
                    tier_summary += f"\n• ... and {len(tier_changes) - 5} more"
            else:
                tier_summary = "• No tier changes"
            
            # Blacklist updates
            newly_blacklisted = blacklist.get("newly_blacklisted", [])
            if newly_blacklisted:
                blacklist_summary = "\n".join([
                    f"• {item['symbol']}: {item['reason']}"
                    for item in newly_blacklisted[:5]
                ])
                if len(newly_blacklisted) > 5:
                    blacklist_summary += f"\n• ... and {len(newly_blacklisted) - 5} more"
            else:
                blacklist_summary = "• No new blacklists"
            
            message = f"""
🔄 <b>Auto-Optimization Report</b>

━━━━━━━━━━━━━━━━━━━━
📊 <b>Performance Summary</b>
• Win Rate: {protection.get('win_rate', 0):.1f}%
• Total Trades: {protection.get('total_trades', 0)}
• Daily PnL: ${protection.get('daily_pnl', 0):+.2f}
• Protection Level: {protection.get('current_level', 'N/A').upper()}

━━━━━━━━━━━━━━━━━━━━
⚙️ <b>Parameter Changes</b>
{param_changes}

━━━━━━━━━━━━━━━━━━━━
📊 <b>Symbol Tiers Updated</b>
• Tier A: {tiering.get('tier_distribution', {}).get('A', 0)} symbols
• Tier B: {tiering.get('tier_distribution', {}).get('B', 0)} symbols
• Tier C: {tiering.get('tier_distribution', {}).get('C', 0)} symbols

<b>Tier Changes:</b>
{tier_summary}

━━━━━━━━━━━━━━━━━━━━
🚫 <b>Blacklist Updates</b>
• Active: {blacklist.get('total_blacklisted', 0)} symbols
• Newly Added: {len(newly_blacklisted)}
• Expired Removed: {blacklist.get('expired_removed', 0)}

<b>New Blacklists:</b>
{blacklist_summary}

━━━━━━━━━━━━━━━━━━━━
⏰ <b>Next Optimization:</b> {self.optimization_interval_hours}h
🕐 {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}
""".strip()
            
            # Send to Telegram
            api_url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(
                    api_url,
                    json={
                        "chat_id": CHAT_ID,
                        "text": message,
                        "parse_mode": "HTML",
                        "disable_web_page_preview": True
                    }
                )
                
                if response.status_code != 200:
                    self.logger.warning(
                        f"⚠️ Telegram API returned {response.status_code}: {response.text[:200]}"
                    )
                    
        except Exception as e:
            self.logger.error(f"❌ Failed to send optimization report: {e}")
    
    async def run_continuous(self):
        """
        Run optimization cycles continuously every N hours.
        
        This is the main entry point for the worker.
        """
        self.logger.info(
            f"🤖 Auto-Optimization Orchestrator started "
            f"(interval: {self.optimization_interval_hours}h)"
        )
        
        while True:
            try:
                # Run optimization cycle
                await self.run_optimization_cycle()
                
                # Wait for next cycle
                sleep_seconds = self.optimization_interval_hours * 3600
                next_run = datetime.utcnow() + timedelta(seconds=sleep_seconds)
                
                self.logger.info(
                    f"😴 Next optimization cycle at {next_run.strftime('%Y-%m-%d %H:%M UTC')}"
                )
                
                await asyncio.sleep(sleep_seconds)
                
            except KeyboardInterrupt:
                self.logger.info("⏹️ Auto-Optimization Orchestrator stopped by user")
                break
            except Exception as e:
                self.logger.error(f"❌ Unexpected error in orchestrator: {e}", exc_info=True)
                # Wait 1 hour before retry on error
                await asyncio.sleep(3600)


async def main():
    """Main entry point for the worker"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    orchestrator = AutoOptimizationOrchestrator()
    await orchestrator.run_continuous()


if __name__ == "__main__":
    asyncio.run(main())
