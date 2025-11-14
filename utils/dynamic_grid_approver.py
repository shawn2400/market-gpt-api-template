# utils/dynamic_grid_approver.py
import os
import time
import logging
from typing import List, Dict, Optional, Any
from dataclasses import dataclass

logger = logging.getLogger("algogpt.grid_approver")

try:
    from utils.binance_client import get_client
    from utils.redis_client import get_redis
except Exception as e:
    logger.warning(f"Failed to import dependencies: {e}")
    get_client = None
    get_redis = None


@dataclass
class GridSymbolScore:
    symbol: str
    grid_score: float
    volume_24h: float
    liquidity: float
    atr_pct: float
    spread_bps: float
    suitable_for_grid: bool
    tier: str
    timestamp: float


class DynamicGridApprover:
    def __init__(self):
        self.client = get_client() if get_client else None
        self.redis = get_redis() if get_redis else None
        
        # 🛡️ RELAXED THRESHOLDS: Increased from strict $75M/$200k to enable 10-20 GRID symbols
        # Previous: $75M volume, $200k liquidity, 3.5% ATR, 10bps spread (only 2 symbols!)
        # Updated: $40M volume, $100k liquidity, 5.0% ATR, 15bps spread (targets 10-20 symbols)
        self.min_volume_grid = 40_000_000      # Was: 75M
        self.max_atr_pct = 0.050               # Was: 0.035 (3.5%)
        self.max_spread_bps = 15               # Was: 10
        self.min_liquidity_grid = 100_000      # Was: 200k
        
        self.grid_approved_key = "grid:approved_list"
        self.grid_tiers_key = "grid:tiers"
        
        logger.info(
            f"DynamicGridApprover initialized - "
            f"min_volume=${self.min_volume_grid/1_000_000:.0f}M, "
            f"max_atr={self.max_atr_pct*100:.1f}%, "
            f"max_spread={self.max_spread_bps}bps, "
            f"min_liquidity=${self.min_liquidity_grid/1_000:.0f}k"
        )
    
    def calculate_grid_approved_list(self, top_50_symbols: List[str]) -> List[str]:
        if not self.client:
            logger.error("Binance client not available")
            return []
        
        scored_symbols = []
        for symbol in top_50_symbols:
            try:
                score = self.calculate_grid_score(symbol)
                if score and score.suitable_for_grid:
                    scored_symbols.append(score)
            except Exception as e:
                logger.debug(f"Failed to score grid {symbol}: {e}")
                continue
        
        scored_symbols.sort(key=lambda x: x.grid_score, reverse=True)
        
        grid_approved = []
        tiers = {'Platinum': [], 'Gold': [], 'Silver': [], 'Bronze': []}
        
        for i, score in enumerate(scored_symbols[:30]):
            grid_approved.append(score.symbol)
            tier = self._assign_tier(i, score.grid_score)
            tiers[tier].append(score.symbol)
        
        self._save_to_redis(grid_approved, tiers)
        
        logger.info(
            f"Grid Approved: {len(grid_approved)} symbols | "
            f"Platinum: {len(tiers['Platinum'])}, "
            f"Gold: {len(tiers['Gold'])}, "
            f"Silver: {len(tiers['Silver'])}, "
            f"Bronze: {len(tiers['Bronze'])}"
        )
        
        return grid_approved
    
    def calculate_grid_score(self, symbol: str) -> Optional[GridSymbolScore]:
        if not self.client:
            return None
        
        try:
            ticker = self.client.futures_ticker(symbol=symbol)
            order_book = self.client.futures_order_book(symbol=symbol, limit=20)
            
            volume_24h = float(ticker.get('quoteVolume', 0))
            price = float(ticker.get('lastPrice', 1))
            
            asks = order_book.get('asks', [])
            bids = order_book.get('bids', [])
            
            if not asks or not bids:
                return None
            
            liquidity = sum(float(ask[1]) * float(ask[0]) for ask in asks[:10])
            liquidity += sum(float(bid[1]) * float(bid[0]) for bid in bids[:10])
            
            best_ask = float(asks[0][0])
            best_bid = float(bids[0][0])
            spread = best_ask - best_bid
            spread_bps = (spread / price) * 10000 if price > 0 else 999
            
            price_change_pct = abs(float(ticker.get('priceChangePercent', 0))) / 100
            atr_pct = price_change_pct
            
            suitable = (
                volume_24h >= self.min_volume_grid and
                atr_pct <= self.max_atr_pct and
                spread_bps <= self.max_spread_bps and
                liquidity >= self.min_liquidity_grid
            )
            
            # 📊 LOG: Rejection reasons for tuning
            if not suitable:
                reasons = []
                if volume_24h < self.min_volume_grid:
                    reasons.append(f"volume={volume_24h/1_000_000:.1f}M<{self.min_volume_grid/1_000_000:.0f}M")
                if atr_pct > self.max_atr_pct:
                    reasons.append(f"atr={atr_pct*100:.1f}%>{self.max_atr_pct*100:.1f}%")
                if spread_bps > self.max_spread_bps:
                    reasons.append(f"spread={spread_bps:.1f}bps>{self.max_spread_bps}bps")
                if liquidity < self.min_liquidity_grid:
                    reasons.append(f"liq=${liquidity/1_000:.0f}k<${self.min_liquidity_grid/1_000:.0f}k")
                logger.debug(f"❌ {symbol}: GRID rejected - {', '.join(reasons)}")
            
            volume_score = self._score_volume(volume_24h)
            liquidity_score = self._score_liquidity(liquidity)
            atr_score = self._score_atr(atr_pct)
            spread_score = self._score_spread(spread_bps)
            
            grid_score = (
                volume_score * 0.30 +
                liquidity_score * 0.30 +
                atr_score * 0.25 +
                spread_score * 0.15
            )
            
            return GridSymbolScore(
                symbol=symbol,
                grid_score=round(grid_score, 2),
                volume_24h=volume_24h,
                liquidity=liquidity,
                atr_pct=atr_pct,
                spread_bps=spread_bps,
                suitable_for_grid=suitable,
                tier='',
                timestamp=time.time()
            )
            
        except Exception as e:
            logger.debug(f"Failed to get grid data for {symbol}: {e}")
            return None
    
    def _score_volume(self, volume: float) -> float:
        if volume > 500_000_000:
            return 100.0
        elif volume > 200_000_000:
            return 90.0
        elif volume > 100_000_000:
            return 80.0
        elif volume > 75_000_000:
            return 70.0
        else:
            return 50.0
    
    def _score_liquidity(self, liquidity: float) -> float:
        if liquidity > 2_000_000:
            return 100.0
        elif liquidity > 1_000_000:
            return 90.0
        elif liquidity > 500_000:
            return 80.0
        elif liquidity > 200_000:
            return 70.0
        else:
            return 50.0
    
    def _score_atr(self, atr_pct: float) -> float:
        if atr_pct < 0.01:
            return 100.0
        elif atr_pct < 0.02:
            return 90.0
        elif atr_pct < 0.03:
            return 75.0
        elif atr_pct <= 0.035:
            return 60.0
        else:
            return 30.0
    
    def _score_spread(self, spread_bps: float) -> float:
        if spread_bps < 2:
            return 100.0
        elif spread_bps < 5:
            return 90.0
        elif spread_bps < 10:
            return 75.0
        else:
            return 50.0
    
    def _assign_tier(self, rank: int, grid_score: float) -> str:
        if rank < 5 and grid_score >= 85:
            return 'Platinum'
        elif rank < 10 and grid_score >= 75:
            return 'Gold'
        elif rank < 20 and grid_score >= 65:
            return 'Silver'
        else:
            return 'Bronze'
    
    def _save_to_redis(self, grid_approved: List[str], tiers: Dict[str, List[str]]):
        if not self.redis:
            return
        
        try:
            import json
            
            self.redis.setex(
                self.grid_approved_key,
                3600,
                json.dumps(grid_approved)
            )
            
            self.redis.setex(
                self.grid_tiers_key,
                3600,
                json.dumps(tiers)
            )
            
            logger.info(f"Saved {len(grid_approved)} grid-approved symbols to Redis")
            
        except Exception as e:
            logger.warning(f"Failed to save grid list to Redis: {e}")
    
    def get_grid_approved_list(self) -> List[str]:
        if not self.redis:
            return []
        
        try:
            import json
            data = self.redis.get(self.grid_approved_key)
            if data:
                return json.loads(data)
        except Exception as e:
            logger.warning(f"Failed to get grid approved list: {e}")
        
        return []
    
    def get_grid_tiers(self) -> Dict[str, List[str]]:
        if not self.redis:
            return {}
        
        try:
            import json
            data = self.redis.get(self.grid_tiers_key)
            if data:
                return json.loads(data)
        except Exception as e:
            logger.warning(f"Failed to get grid tiers: {e}")
        
        return {}
    
    def is_grid_approved(self, symbol: str) -> bool:
        approved_list = self.get_grid_approved_list()
        return symbol.upper() in [s.upper() for s in approved_list]
    
    def get_symbol_tier(self, symbol: str) -> Optional[str]:
        tiers = self.get_grid_tiers()
        for tier, symbols in tiers.items():
            if symbol.upper() in [s.upper() for s in symbols]:
                return tier
        return None


_approver_instance: Optional[DynamicGridApprover] = None

def get_grid_approver() -> DynamicGridApprover:
    global _approver_instance
    if _approver_instance is None:
        _approver_instance = DynamicGridApprover()
    return _approver_instance
