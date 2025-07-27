import json
import os
from datetime import datetime

def save_trade_snapshot(symbol, direction, forecast, chart_base64):
    if not os.path.exists("snapshots"):
        os.makedirs("snapshots")

    now = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"snapshots/{symbol}_{direction}_{now}.json"

    data = {
        "symbol": symbol,
        "direction": direction,
        "timestamp": now,
        "forecast": forecast[['ds', 'yhat', 'yhat_lower', 'yhat_upper']].tail(6).to_dict(orient='records'),
        "chart_base64": chart_base64
    }

    with open(filename, "w") as f:
        json.dump(data, f, indent=2)


