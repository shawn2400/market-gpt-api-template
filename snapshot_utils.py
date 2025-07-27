import os
import json
from datetime import datetime

def save_trade_snapshot(trade):
    folder = "snapshots"
    if not os.path.exists(folder):
        os.makedirs(folder)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    symbol = trade.get("symbol", "UNKNOWN")
    filename = f"{symbol}_{timestamp}.json"
    path = os.path.join(folder, filename)

    with open(path, "w") as f:
        json.dump(trade, f, indent=2)



