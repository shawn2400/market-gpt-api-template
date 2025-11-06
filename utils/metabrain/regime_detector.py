"""
Regime Detector - MetaBrain v9.0
Automatically detects current market regime (TRENDING/CHOPPY/VOLATILE/SIDEWAYS)
Based on technical indicators: ADX, ATR, Bollinger Bands
"""
import logging
from typing import Dict, Literal

log = logging.getLogger(__name__)

MarketRegime = Literal["TRENDING", "CHOPPY", "VOLATILE", "SIDEWAYS"]

class RegimeDetector:
    """
    Detects market regime based on technical indicators
    
    TRENDING: ADX > 25, clear direction
    CHOPPY: ADX < 20, no clear trend
    VOLATILE: ATR high, Bollinger Bands wide
    SIDEWAYS: ATR low, price in narrow range
    """
    
    def detect_regime(self, indicators: Dict) -> MarketRegime:
        """
        Detect market regime from technical indicators
        
        Args:
            indicators: Dict with keys: adx, atr, bb_width, price_range_pct
        
        Returns:
            MarketRegime: TRENDING, CHOPPY, VOLATILE, or SIDEWAYS
        """
        adx = indicators.get("adx", 0)
        atr = indicators.get("atr", 0)
        bb_width = indicators.get("bb_width", 0)
        price_range = indicators.get("price_range_pct", 0)
        
        volatility_score = self._calculate_volatility_score(atr, bb_width, price_range)
        trend_score = adx
        
        regime = self._classify_regime(trend_score, volatility_score)
        
        log.debug(f"Regime Detection: ADX={adx:.1f}, Vol={volatility_score:.1f} → {regime}")
        
        return regime
    
    def _calculate_volatility_score(self, atr: float, bb_width: float, price_range: float) -> float:
        """
        Calculate volatility score from multiple indicators
        Higher score = more volatile
        """
        atr_normalized = min(atr / 0.02, 100)
        
        bb_normalized = min(bb_width / 0.04, 100)
        
        range_normalized = min(price_range / 3.0, 100)
        
        volatility = (atr_normalized * 0.5 + bb_normalized * 0.3 + range_normalized * 0.2)
        
        return volatility
    
    def _classify_regime(self, trend_score: float, volatility_score: float) -> MarketRegime:
        """
        Classify regime based on trend and volatility scores
        
        Logic:
        - High trend + any volatility → TRENDING
        - Low trend + high volatility → VOLATILE
        - Low trend + low volatility → SIDEWAYS
        - Medium trend + any volatility → CHOPPY
        """
        if trend_score > 25:
            return "TRENDING"
        
        elif trend_score < 20:
            if volatility_score > 60:
                return "VOLATILE"
            else:
                return "SIDEWAYS"
        
        else:
            return "CHOPPY"
    
    def get_regime_description(self, regime: MarketRegime) -> str:
        """Get human-readable description of regime"""
        descriptions = {
            "TRENDING": "📈 גל חזק - מומנטום ברור, נסיעה על הטרנד",
            "CHOPPY": "🌊 ים סוער - אין כיוון ברור, ויפסאו",
            "VOLATILE": "⚡ סערה - תנודתיות גבוהה, תנועות ענקיות",
            "SIDEWAYS": "↔️ שטוח - טווח צר, המתנה לפריצה"
        }
        return descriptions.get(regime, "Unknown")


regime_detector = RegimeDetector()
