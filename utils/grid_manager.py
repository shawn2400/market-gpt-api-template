# utils/grid_manager.py
from typing import List, Dict, Any
import time

# מחזיר רשימת גרידים דמו
def get_grid_status() -> List[Dict[str, Any]]:
    return [
        {
            "id": "grid_1",
            "symbol": "BTCUSDT",
            "levels": 5,
            "allocated": 100.0,
            "profit_pct": 2.5,
            "active": True,
        },
        {
            "id": "grid_2",
            "symbol": "ETHUSDT",
            "levels": 4,
            "allocated": 50.0,
            "profit_pct": -1.2,
            "active": False,
        },
    ]

# מחזיר רק גרידים אקטיביים
def get_active_grids() -> List[Dict[str, Any]]:
    return [g for g in get_grid_status() if g["active"]]
