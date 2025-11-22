"""
Data Fusion — Combine insights from all external sources
"""
import logging
from typing import Dict, Any, List

logger = logging.getLogger("DataFusion")

class DataFusion:
    @staticmethod
    def merge_market_data(sources: Dict[str, Any]) -> Dict[str, Any]:
        """
        Merge market data from multiple sources
        Cryptohopper, TradingView, Bybit, etc.
        """
        fused = {
            "price": 0,
            "volume": 0,
            "momentum": 0,
            "trend": "NEUTRAL",
            "sources": []
        }
        
        total_sources = len(sources)
        if total_sources == 0:
            return fused
        
        prices = []
        volumes = []
        momenta = []
        
        for source, data in sources.items():
            if "price" in data:
                prices.append(data["price"])
            if "volume" in data:
                volumes.append(data["volume"])
            if "momentum" in data:
                momenta.append(data["momentum"])
            
            fused["sources"].append(source)
        
        # Average
        if prices:
            fused["price"] = sum(prices) / len(prices)
        if volumes:
            fused["volume"] = sum(volumes) / len(volumes)
        if momenta:
            fused["momentum"] = sum(momenta) / len(momenta)
            
            # Determine trend
            if fused["momentum"] > 0.5:
                fused["trend"] = "BULLISH"
            elif fused["momentum"] < -0.5:
                fused["trend"] = "BEARISH"
        
        return fused
