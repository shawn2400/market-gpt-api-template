"""
Self Optimizer — Score bots and learn from performance
"""
import logging
from typing import Dict, Any, List

logger = logging.getLogger("SelfOptimizer")

class SelfOptimizer:
    def __init__(self):
        self.bot_scores = {}
        self.bot_results = {}
    
    def evaluate(self, trade_results: List[Dict[str, Any]]) -> Dict[str, float]:
        """
        Score each bot based on trade results
        Bots that suggested winning trades get higher scores
        """
        scores = {}
        
        for result in trade_results:
            bot = result.get("source", "unknown")
            outcome = result.get("outcome", 0)  # 1 = win, 0 = loss
            
            if bot not in scores:
                scores[bot] = {"wins": 0, "total": 0}
            
            scores[bot]["total"] += 1
            if outcome > 0:
                scores[bot]["wins"] += 1
        
        # Calculate win rate (0-10 scale)
        final_scores = {}
        for bot, stats in scores.items():
            win_rate = (stats["wins"] / max(stats["total"], 1)) * 10
            final_scores[bot] = round(win_rate, 2)
            logger.info(f"🧠 {bot}: {stats['wins']}/{stats['total']} wins (Score: {final_scores[bot]}/10)")
        
        self.bot_scores = final_scores
        return final_scores
    
    def adjust_plugin_weights(self, plugin_manager):
        """
        Auto-adjust plugin mode based on scores
        High score bots: ON
        Low score bots: OFF or AUTO
        """
        for name, score in self.bot_scores.items():
            plugin = plugin_manager.get(name)
            if not plugin:
                continue
            
            if score >= 7:
                plugin.enable()
                logger.info(f"🟢 {name}: ON (high score: {score})")
            elif score >= 4:
                logger.info(f"🟡 {name}: AUTO (medium score: {score})")
            else:
                plugin.disable()
                logger.info(f"🔴 {name}: OFF (low score: {score})")
