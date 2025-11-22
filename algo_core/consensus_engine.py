"""
Consensus Engine — Merge signals from multiple sources
"""
import logging
from typing import Dict, Any, List

logger = logging.getLogger("ConsensusEngine")

class ConsensusEngine:
    def merge(self, scans: List[Dict[str, Any]], signals: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Merge scan data + signals + indicators
        Return ranked list of best opportunities
        """
        fused = {}
        
        # Process scans
        for scan in scans:
            for item in scan.get("data", []):
                symbol = item.get("symbol", "")
                score = item.get("score", 0)
                
                if symbol not in fused:
                    fused[symbol] = {
                        "symbol": symbol,
                        "score": 0,
                        "sources": [],
                        "data": {}
                    }
                
                fused[symbol]["score"] += score * 0.6  # Scans weighted 60%
                fused[symbol]["sources"].append(scan["source"])
                fused[symbol]["data"][scan["source"]] = item
        
        # Process signals
        for sig in signals:
            symbol = sig.get("symbol", "")
            score = sig.get("score", 10)
            
            if symbol not in fused:
                fused[symbol] = {
                    "symbol": symbol,
                    "score": 0,
                    "sources": [],
                    "data": {}
                }
            
            fused[symbol]["score"] += score * 0.4  # Signals weighted 40%
            fused[symbol]["sources"].append(sig.get("source", "unknown"))
        
        # Normalize scores (0-10)
        if fused:
            max_score = max(item["score"] for item in fused.values())
            if max_score > 0:
                for item in fused.values():
                    item["score"] = (item["score"] / max_score) * 10
        
        # Sort by score
        result = sorted(fused.values(), key=lambda x: x["score"], reverse=True)
        
        logger.info(f"✅ Merged {len(scans)} scans + {len(signals)} signals → {len(result)} candidates")
        
        return result[:20]  # Top 20 opportunities
