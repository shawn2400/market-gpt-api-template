# -*- coding: utf-8 -*-
"""
ULTRA-PLUS: ML Predictor - 5-15 minute price direction forecasting.
Dynamic auto-activation based on price data availability.
"""

import os
import logging
from collections import deque
from typing import Optional, Dict, Any
from contextlib import suppress

logger = logging.getLogger(__name__)

# Dynamic config
ENABLE_ML_PREDICTOR = os.getenv("ENABLE_ML_PREDICTOR", "1") == "1"
ML_WINDOW = int(os.getenv("ML_WINDOW", "50"))
ML_THRESHOLD_ENTER = float(os.getenv("ML_THRESHOLD_ENTER", "0.62"))
ML_THRESHOLD_EXIT = float(os.getenv("ML_THRESHOLD_EXIT", "0.18"))


class MLPredictor:
    """Simple ML-based price direction predictor using polynomial regression."""
    
    def __init__(self, window: int = ML_WINDOW):
        self.enabled = ENABLE_ML_PREDICTOR
        self.window = window
        self.prices = deque(maxlen=window)
        self.last_prediction = None
    
    def update(self, price: float) -> None:
        """Update predictor with new price data."""
        if price and price > 0:
            self.prices.append(price)
    
    def predict(self) -> Optional[Dict[str, Any]]:
        """
        Predict price direction for next 5-15 minutes.
        Returns: {"direction": "UP"|"DOWN"|"FLAT", "confidence": 0.0-1.0}
        """
        if not self.enabled or len(self.prices) < max(3, self.window // 2):
            return None
        
        with suppress(Exception):
            import numpy as np
            
            x = np.arange(len(self.prices))
            y = np.array(self.prices, dtype=float)
            
            # Polynomial regression (degree 1 = linear)
            coeff = np.polyfit(x, y, 1)
            slope = coeff[0]
            
            # Convert slope to confidence (0.0-1.0)
            # Higher slope = higher confidence in UP trend
            if slope > 0:
                confidence = min(abs(slope) * 100, 1.0)  # Scale slope to 0-1
                direction = "UP"
            elif slope < 0:
                confidence = min(abs(slope) * 100, 1.0)
                direction = "DOWN"
            else:
                confidence = 0.1
                direction = "FLAT"
            
            prediction = {
                "direction": direction,
                "confidence": round(confidence, 3),
                "slope": round(slope, 6),
                "window_size": len(self.prices),
                "timestamp": None
            }
            
            self.last_prediction = prediction
            return prediction
        
        return None
    
    def should_enter(self, prediction: Optional[Dict[str, Any]] = None) -> bool:
        """Check if prediction suggests entering a trade."""
        if not prediction:
            prediction = self.last_prediction
        if not prediction:
            return False
        
        return prediction["confidence"] >= ML_THRESHOLD_ENTER
    
    def should_exit(self, prediction: Optional[Dict[str, Any]] = None) -> bool:
        """Check if prediction suggests exiting a trade."""
        if not prediction:
            prediction = self.last_prediction
        if not prediction:
            return False
        
        return prediction["confidence"] <= ML_THRESHOLD_EXIT
    
    def get_direction_bias(self) -> Optional[str]:
        """Get current directional bias (UP/DOWN/FLAT)."""
        if self.last_prediction:
            return self.last_prediction["direction"]
        return None
    
    def reset(self) -> None:
        """Reset predictor state."""
        self.prices.clear()
        self.last_prediction = None


# Global singleton
_ml_predictor = None


def get_ml_predictor() -> MLPredictor:
    """Get or create global ML predictor (singleton)."""
    global _ml_predictor
    if _ml_predictor is None:
        _ml_predictor = MLPredictor()
        if ENABLE_ML_PREDICTOR:
            logger.info("✅ ML Predictor initialized (dynamic auto-activation enabled)")
        else:
            logger.info("ℹ️  ML Predictor disabled")
    return _ml_predictor
