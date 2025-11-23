# -*- coding: utf-8 -*-
"""
ULTRA-PLUS: Anomaly Detector - Detects fraud and crash patterns.
Dynamic auto-activation when unusual trading patterns emerge.
"""

import os
import logging
from collections import deque
from typing import Dict, Any, Optional, List
from contextlib import suppress

logger = logging.getLogger(__name__)

# Dynamic config
ENABLE_ANOMALY_DETECTOR = os.getenv("ENABLE_ANOMALY_DETECTOR", "1") == "1"
ANOMALY_WINDOW = int(os.getenv("ANOMALY_WINDOW", "10"))  # Last N trades
FULL_RED_THRESHOLD = int(os.getenv("FULL_RED_THRESHOLD", "5"))  # N consecutive losses
SEVERE_LOSS_THRESHOLD = float(os.getenv("SEVERE_LOSS_THRESHOLD", "0.12"))  # Cumulative loss


class AnomalyDetector:
    """
    Detects trading anomalies and crash patterns.
    Automatically pauses trading if severe issues detected.
    """
    
    def __init__(self, window_size: int = ANOMALY_WINDOW):
        self.enabled = ENABLE_ANOMALY_DETECTOR
        self.window_size = window_size
        self.trades = deque(maxlen=window_size)
        self.anomaly_count = 0
        self.last_anomaly = None
    
    def add_trade(self, pnl: float, symbol: str = "", side: str = "") -> None:
        """
        Add a completed trade to the anomaly detection window.
        
        Args:
            pnl: Trade PnL
            symbol: Trading symbol
            side: Trade side (BUY/SELL)
        """
        self.trades.append({
            "pnl": pnl,
            "symbol": symbol,
            "side": side
        })
    
    def detect_full_red(self) -> bool:
        """
        Detect if last N trades are all losses (full red pattern).
        Indicates systematic failure.
        
        Returns:
            True if anomaly detected
        """
        if len(self.trades) < FULL_RED_THRESHOLD:
            return False
        
        recent = list(self.trades)[-FULL_RED_THRESHOLD:]
        all_losses = all(t["pnl"] < 0 for t in recent)
        
        return all_losses
    
    def detect_severe_drawdown(self) -> bool:
        """
        Detect if cumulative loss in window exceeds threshold.
        Indicates rapid account degradation.
        
        Returns:
            True if anomaly detected
        """
        if not self.trades:
            return False
        
        total_loss = sum(t["pnl"] for t in self.trades if t["pnl"] < 0)
        
        return abs(total_loss) > SEVERE_LOSS_THRESHOLD
    
    def detect_symbol_crush(self, symbol: str = None) -> bool:
        """
        Detect if a specific symbol is consistently losing.
        Indicates problematic symbol selection.
        
        Args:
            symbol: Symbol to check (optional, checks last N trades if not specified)
        
        Returns:
            True if anomaly detected
        """
        if not self.trades:
            return False
        
        trades_to_check = list(self.trades)
        
        if symbol:
            trades_to_check = [t for t in trades_to_check if t.get("symbol") == symbol]
        
        if len(trades_to_check) < 3:
            return False
        
        losses = [t for t in trades_to_check if t["pnl"] < 0]
        loss_rate = len(losses) / len(trades_to_check)
        
        return loss_rate >= 0.8  # 80%+ loss rate
    
    def detect(self) -> Optional[Dict[str, Any]]:
        """
        Run full anomaly detection.
        Returns type and severity if anomaly found.
        
        Returns:
            Anomaly info or None
        """
        if not self.enabled or not self.trades:
            return None
        
        anomaly = None
        
        # Check for full red
        if self.detect_full_red():
            anomaly = {
                "type": "FULL_RED",
                "severity": "CRITICAL",
                "reason": f"Last {FULL_RED_THRESHOLD} trades all losses",
                "action": "AUTO_PAUSE",
                "trades_analyzed": len(self.trades)
            }
        
        # Check for severe drawdown
        elif self.detect_severe_drawdown():
            anomaly = {
                "type": "SEVERE_DRAWDOWN",
                "severity": "HIGH",
                "reason": f"Cumulative loss > ${SEVERE_LOSS_THRESHOLD:.2f}",
                "action": "REDUCE_SIZE",
                "trades_analyzed": len(self.trades)
            }
        
        # Check for symbol crush
        elif self.detect_symbol_crush():
            worst_symbol = self._get_worst_symbol()
            anomaly = {
                "type": "SYMBOL_CRUSH",
                "severity": "MEDIUM",
                "reason": f"Symbol {worst_symbol} has 80%+ loss rate",
                "action": "FREEZE_SYMBOL",
                "symbol": worst_symbol,
                "trades_analyzed": len(self.trades)
            }
        
        if anomaly:
            self.anomaly_count += 1
            self.last_anomaly = anomaly
            logger.warning(
                f"🚨 Anomaly detected: {anomaly['type']} ({anomaly['severity']}) → "
                f"{anomaly['action']}"
            )
        
        return anomaly
    
    def _get_worst_symbol(self) -> str:
        """Get symbol with worst performance in window."""
        symbol_pnls: Dict[str, List[float]] = {}
        
        for trade in self.trades:
            symbol = trade.get("symbol", "UNKNOWN")
            if symbol not in symbol_pnls:
                symbol_pnls[symbol] = []
            symbol_pnls[symbol].append(trade["pnl"])
        
        worst_symbol = "UNKNOWN"
        worst_rate = -1.0
        
        for symbol, pnls in symbol_pnls.items():
            if not pnls:
                continue
            losses = len([p for p in pnls if p < 0])
            loss_rate = losses / len(pnls)
            if loss_rate > worst_rate:
                worst_rate = loss_rate
                worst_symbol = symbol
        
        return worst_symbol
    
    def get_stats(self) -> Dict[str, Any]:
        """Get detector statistics."""
        if not self.trades:
            return {"trades_analyzed": 0, "anomalies_detected": 0}
        
        pnls = [t["pnl"] for t in self.trades]
        losses = len([p for p in pnls if p < 0])
        
        return {
            "trades_analyzed": len(self.trades),
            "anomalies_detected": self.anomaly_count,
            "loss_rate": round(losses / len(pnls) if pnls else 0, 3),
            "total_pnl": round(sum(pnls), 2),
            "last_anomaly": self.last_anomaly
        }
    
    def reset(self) -> None:
        """Reset detector state."""
        self.trades.clear()
        self.anomaly_count = 0
        self.last_anomaly = None
        logger.info("🔄 Anomaly detector reset")


# Global singleton
_anomaly_detector = None


def get_anomaly_detector() -> AnomalyDetector:
    """Get or create global anomaly detector (singleton)."""
    global _anomaly_detector
    if _anomaly_detector is None:
        _anomaly_detector = AnomalyDetector()
        if ENABLE_ANOMALY_DETECTOR:
            logger.info("✅ Anomaly Detector initialized (dynamic auto-activation enabled)")
        else:
            logger.info("ℹ️  Anomaly Detector disabled")
    return _anomaly_detector
