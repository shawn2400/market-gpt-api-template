# utils/correlation.py
from typing import List, Dict, Any
import numpy as np
import logging

logger = logging.getLogger("algogpt.correlation")

def correlate_to_btc(
    symbols: List[str],
    ref_symbol: str = "BTCUSDT",
    timeframe: str = "15m",
    window: int = 200
) -> List[Dict[str, Any]]:
    """
    מחשב מתאם פירסון בין כל סימול ל-BTC (ref_symbol).
    כרגע DEMO בלבד – מחזיר מתאם רנדומלי.
    """
    results: List[Dict[str, Any]] = []
    for sym in symbols:
        try:
            corr = float(np.random.uniform(-1, 1))
            results.append({"symbol": sym, "ref": ref_symbol, "correlation": corr})
        except Exception as e:
            logger.error(f"Failed correlation calc for {sym}: {e}")
            results.append({"symbol": sym, "ref": ref_symbol, "error": str(e)})
    return results






