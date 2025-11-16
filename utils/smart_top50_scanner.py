# utils/smart_top50_scanner.py
import os
import time
import random
import logging
from typing import List, Dict, Optional, Any
from dataclasses import dataclass

logger = logging.getLogger("algogpt.top50_scanner")

try:
    from utils.binance_client import get_client
    from utils.redis_client import get_redis
except Exception as e:
    logger.warning(f"Failed to import dependencies: {e}")
    get_client = None
    get_redis = None


@dataclass
class SymbolScore:
    symbol: str
    total_score: float
    volume_24h: float
    liquidity: float
    volume_score: float
    liquidity_score: float
    volatility_score: float
    timestamp: float


class SmartTop50Scanner:
    def __init__(self):
        self.client = get_client() if get_client else None
        self.redis = get_redis() if get_redis else None
        self.candidate_pool_size = 160  # Expanded from 120 to 160
        self.previous_top_100_key = "top50:previous_top_100"
        self.min_volume_24h = 10_000_000  # Lowered from $20M to $10M to allow more symbols
        self.min_liquidity = 50_000  # Lowered from $100k to $50k to allow more symbols
        
        logger.info("SmartTop50Scanner initialized - scanning 160 candidates instead of 538")
    
    def get_optimized_candidate_pool(self) -> List[str]:
        if not self.client:
            logger.error("Binance client not available")
            return []
        
        all_symbols = self._get_all_symbols()
        previous_top_100 = self._get_previous_top_100()
        
        candidates = []
        if previous_top_100:
            candidates = previous_top_100[:100]  # Expanded from 80 to 100
            logger.info(f"Added 100 symbols from previous TOP 100")
        else:
            logger.info("No previous TOP 100, using random sample")
        
        remaining_symbols = [s for s in all_symbols if s not in candidates]
        new_candidates_count = min(60, len(remaining_symbols))  # Expanded from 40 to 60
        if new_candidates_count > 0:
            new_candidates = random.sample(remaining_symbols, new_candidates_count)
            candidates.extend(new_candidates)
            logger.info(f"Added {new_candidates_count} new random candidates")
        
        logger.info(f"Candidate pool: {len(candidates)} symbols (target: 160, vs 538 full scan)")
        return candidates
    
    def _get_all_symbols(self) -> List[str]:
        if not self.client:
            return []
        try:
            exinfo = self.client.futures_exchange_info()
            symbols = [
                s['symbol'] for s in exinfo.get('symbols', [])
                if s.get('status') == 'TRADING' and s.get('quoteAsset') == 'USDT'
            ]
            return symbols
        except Exception as e:
            logger.error(f"Failed to get all symbols: {e}")
            return []
    
    def _get_previous_top_100(self) -> List[str]:
        if not self.redis:
            return []
        
        try:
            data = self.redis.get(self.previous_top_100_key)
            if data:
                import json
                return json.loads(data)
        except Exception as e:
            logger.warning(f"Failed to get previous TOP 100: {e}")
        
        return []
    
    def _save_top_100(self, symbols: List[str]):
        if not self.redis:
            return
        
        try:
            import json
            self.redis.setex(
                self.previous_top_100_key,
                86400,
                json.dumps(symbols[:100])
            )
            logger.info(f"Saved TOP 100 to Redis for next scan")
        except Exception as e:
            logger.warning(f"Failed to save TOP 100: {e}")
    
    def calculate_optimized_top_50(self) -> List[str]:
        candidate_pool = self.get_optimized_candidate_pool()
        
        if not candidate_pool:
            logger.error("No candidates to scan")
            return []
        
        scored_symbols = []
        for symbol in candidate_pool:
            try:
                score = self.calculate_symbol_score(symbol)
                if score:
                    scored_symbols.append(score)
            except Exception as e:
                logger.debug(f"Failed to score {symbol}: {e}")
                continue
        
        scored_symbols.sort(key=lambda x: x.total_score, reverse=True)
        
        top_50 = [s.symbol for s in scored_symbols[:50]]
        top_100_for_next = [s.symbol for s in scored_symbols[:100]]
        
        self._save_top_100(top_100_for_next)
        
        logger.info(
            f"Calculated TOP 50 from {len(candidate_pool)} candidates | "
            f"Best score: {scored_symbols[0].total_score if scored_symbols else 0:.2f}"
        )
        
        return top_50
    
    def calculate_symbol_score(self, symbol: str) -> Optional[SymbolScore]:
        symbol_data = self.get_symbol_data(symbol)
        if not symbol_data:
            return None
        
        if symbol_data['volume_24h'] < self.min_volume_24h:
            return None
        
        if symbol_data['liquidity'] < self.min_liquidity:
            return None
        
        volume_score = self._calculate_volume_score(symbol_data['volume_24h'])
        liquidity_score = self._calculate_liquidity_score(symbol_data['liquidity'])
        volatility_score = self._calculate_volatility_score(symbol_data.get('atr_pct', 0))
        
        weights = {
            'volume': 0.35,
            'liquidity': 0.35,
            'volatility': 0.30
        }
        
        total_score = (
            volume_score * weights['volume'] +
            liquidity_score * weights['liquidity'] +
            volatility_score * weights['volatility']
        )
        
        return SymbolScore(
            symbol=symbol,
            total_score=round(total_score, 2),
            volume_24h=symbol_data['volume_24h'],
            liquidity=symbol_data['liquidity'],
            volume_score=volume_score,
            liquidity_score=liquidity_score,
            volatility_score=volatility_score,
            timestamp=time.time()
        )
    
    def get_symbol_data(self, symbol: str) -> Optional[Dict[str, Any]]:
        if not self.client:
            return None
        try:
            ticker = self.client.futures_ticker(symbol=symbol)
            order_book = self.client.futures_order_book(symbol=symbol, limit=20)
            
            volume_24h = float(ticker.get('quoteVolume', 0))
            
            asks = order_book.get('asks', [])
            bids = order_book.get('bids', [])
            liquidity = sum(float(ask[1]) * float(ask[0]) for ask in asks[:10])
            liquidity += sum(float(bid[1]) * float(bid[0]) for bid in bids[:10])
            
            price_change_pct = abs(float(ticker.get('priceChangePercent', 0))) / 100
            atr_pct = price_change_pct
            
            return {
                'volume_24h': volume_24h,
                'liquidity': liquidity,
                'atr_pct': atr_pct,
                'price': float(ticker.get('lastPrice', 0))
            }
            
        except Exception as e:
            logger.debug(f"Failed to get data for {symbol}: {e}")
            return None
    
    def _calculate_volume_score(self, volume: float) -> float:
        if volume > 500_000_000:
            return 100.0
        elif volume > 200_000_000:
            return 90.0
        elif volume > 100_000_000:
            return 80.0
        elif volume > 50_000_000:
            return 70.0
        elif volume > 20_000_000:
            return 60.0
        else:
            return 0.0
    
    def _calculate_liquidity_score(self, liquidity: float) -> float:
        if liquidity > 1_000_000:
            return 100.0
        elif liquidity > 500_000:
            return 90.0
        elif liquidity > 250_000:
            return 80.0
        elif liquidity > 100_000:
            return 70.0
        else:
            return 0.0
    
    def _calculate_volatility_score(self, atr_pct: float) -> float:
        if 0.01 <= atr_pct <= 0.04:
            return 100.0
        elif 0.005 <= atr_pct <= 0.06:
            return 80.0
        elif atr_pct < 0.005:
            return 60.0
        else:
            return 40.0


_scanner_instance: Optional[SmartTop50Scanner] = None

def get_smart_scanner() -> SmartTop50Scanner:
    global _scanner_instance
    if _scanner_instance is None:
        _scanner_instance = SmartTop50Scanner()
    return _scanner_instance
