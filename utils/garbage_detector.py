# utils/garbage_detector.py
import os
import time
import logging
from typing import List, Dict, Optional, Any
from dataclasses import dataclass
from collections import defaultdict

logger = logging.getLogger("algogpt.garbage_detector")

try:
    from utils.binance_client import get_client
    from utils.redis_client import get_redis
    from utils.zero_tolerance_gatekeeper import get_gatekeeper
except Exception as e:
    logger.warning(f"Failed to import dependencies: {e}")
    get_client = None
    get_redis = None
    get_gatekeeper = None


@dataclass
class SymbolPerformance:
    symbol: str
    total_trades: int
    wins: int
    losses: int
    win_rate: float
    avg_pnl_pct: float
    consecutive_losses: int
    volume_24h: float
    is_garbage: bool
    garbage_reasons: List[str]


class GarbageDetector:
    def __init__(self):
        self.client = get_client() if get_client else None
        self.redis = get_redis() if get_redis else None
        self.gatekeeper = get_gatekeeper() if get_gatekeeper else None
        
        self.min_trades_for_evaluation = 3
        self.max_consecutive_losses = 3
        self.min_acceptable_win_rate = 0.35
        self.max_acceptable_avg_loss = -0.05
        self.min_acceptable_volume = 10_000_000
        
        logger.info(
            "GarbageDetector initialized - "
            f"min_winrate={self.min_acceptable_win_rate*100:.0f}%, "
            f"max_consecutive_losses={self.max_consecutive_losses}"
        )
    
    def scan_for_garbage(self, top_50_symbols: List[str]) -> List[str]:
        garbage_symbols = []
        
        for symbol in top_50_symbols:
            try:
                performance = self.analyze_symbol_performance(symbol)
                if performance and performance.is_garbage:
                    garbage_symbols.append(symbol)
                    
                    if self.gatekeeper:
                        reasons_str = ', '.join(performance.garbage_reasons)
                        self.gatekeeper.add_to_permanent_blacklist(
                            symbol,
                            f"Garbage detected: {reasons_str}"
                        )
                        
                        logger.warning(
                            f"💀 GARBAGE DETECTED: {symbol} | "
                            f"WinRate={performance.win_rate*100:.1f}%, "
                            f"ConsecLosses={performance.consecutive_losses}, "
                            f"Reasons: {reasons_str}"
                        )
            except Exception as e:
                logger.debug(f"Failed to analyze {symbol}: {e}")
                continue
        
        logger.info(
            f"Garbage scan complete: {len(garbage_symbols)} trash symbols found"
        )
        
        return garbage_symbols
    
    def analyze_symbol_performance(self, symbol: str) -> Optional[SymbolPerformance]:
        trade_history = self._get_trade_history(symbol)
        
        if not trade_history or len(trade_history) < self.min_trades_for_evaluation:
            return None
        
        total_trades = len(trade_history)
        wins = sum(1 for t in trade_history if t.get('pnl_pct', 0) > 0)
        losses = sum(1 for t in trade_history if t.get('pnl_pct', 0) < 0)
        
        win_rate = wins / total_trades if total_trades > 0 else 0
        
        avg_pnl_pct = sum(t.get('pnl_pct', 0) for t in trade_history) / total_trades
        
        consecutive_losses = self._calculate_consecutive_losses(trade_history)
        
        volume_24h = self._get_24h_volume(symbol)
        
        is_garbage = False
        garbage_reasons = []
        
        if consecutive_losses >= self.max_consecutive_losses:
            is_garbage = True
            garbage_reasons.append(f"{consecutive_losses} consecutive losses")
        
        if win_rate < self.min_acceptable_win_rate and total_trades >= 5:
            is_garbage = True
            garbage_reasons.append(f"WinRate {win_rate*100:.1f}% < {self.min_acceptable_win_rate*100:.0f}%")
        
        if avg_pnl_pct < self.max_acceptable_avg_loss:
            is_garbage = True
            garbage_reasons.append(f"AvgPnL {avg_pnl_pct*100:.1f}% < {self.max_acceptable_avg_loss*100:.0f}%")
        
        if volume_24h < self.min_acceptable_volume:
            is_garbage = True
            garbage_reasons.append(f"Volume ${volume_24h/1_000_000:.1f}M < ${self.min_acceptable_volume/1_000_000:.0f}M")
        
        return SymbolPerformance(
            symbol=symbol,
            total_trades=total_trades,
            wins=wins,
            losses=losses,
            win_rate=win_rate,
            avg_pnl_pct=avg_pnl_pct,
            consecutive_losses=consecutive_losses,
            volume_24h=volume_24h,
            is_garbage=is_garbage,
            garbage_reasons=garbage_reasons
        )
    
    def _get_trade_history(self, symbol: str) -> List[Dict[str, Any]]:
        if not self.redis:
            return []
        
        try:
            import json
            key = f"performance:trades:{symbol.upper()}"
            data = self.redis.get(key)
            if data:
                return json.loads(data)
        except Exception as e:
            logger.debug(f"Failed to get trade history for {symbol}: {e}")
        
        return []
    
    def _calculate_consecutive_losses(self, trade_history: List[Dict[str, Any]]) -> int:
        consecutive = 0
        for trade in reversed(trade_history):
            if trade.get('pnl_pct', 0) < 0:
                consecutive += 1
            else:
                break
        return consecutive
    
    def _get_24h_volume(self, symbol: str) -> float:
        if not self.client:
            return 0.0
        
        try:
            ticker = self.client.futures_ticker(symbol=symbol)
            return float(ticker.get('quoteVolume', 0))
        except Exception as e:
            logger.debug(f"Failed to get volume for {symbol}: {e}")
            return 0.0
    
    def record_trade_result(
        self,
        symbol: str,
        pnl_pct: float,
        pnl_usdt: float,
        entry_time: float,
        exit_time: float
    ):
        if not self.redis:
            return
        
        try:
            import json
            key = f"performance:trades:{symbol.upper()}"
            
            trade_record = {
                'symbol': symbol,
                'pnl_pct': pnl_pct,
                'pnl_usdt': pnl_usdt,
                'entry_time': entry_time,
                'exit_time': exit_time,
                'timestamp': time.time()
            }
            
            data = self.redis.get(key)
            history = json.loads(data) if data else []
            
            history.append(trade_record)
            
            history = history[-50:]
            
            self.redis.setex(key, 86400 * 7, json.dumps(history))
            
            logger.debug(f"Recorded trade for {symbol}: PnL {pnl_pct*100:.2f}%")
            
        except Exception as e:
            logger.warning(f"Failed to record trade for {symbol}: {e}")


_detector_instance: Optional[GarbageDetector] = None

def get_garbage_detector() -> GarbageDetector:
    global _detector_instance
    if _detector_instance is None:
        _detector_instance = GarbageDetector()
    return _detector_instance
