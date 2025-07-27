import matplotlib.pyplot as plt
import os
import base64
from datetime import datetime

def save_trade_snapshot(trade):
    try:
        symbol = trade.get("symbol", "UNKNOWN")
        entry = trade.get("entry")
        stop = trade.get("stop")
        tp = trade.get("tp")
        direction = trade.get("direction", "LONG")
        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

        fig, ax = plt.subplots(figsize=(6, 4))
        ax.axhline(entry, color="blue", linestyle="--", label="Entry")
        ax.axhline(stop, color="red", linestyle="--", label="Stop Loss")
        ax.axhline(tp, color="green", linestyle="--", label="Take Profit")
        ax.set_title(f"{symbol} Trade ({direction})")
        ax.set_xlabel("Time")
        ax.set_ylabel("Price")
        ax.legend()

        os.makedirs("snapshots", exist_ok=True)
        filename = f"snapshots/{symbol}_{timestamp.replace(':', '-')}.png"
        plt.savefig(filename)
        plt.close(fig)

        return filename
    except Exception as e:
        print("Error saving snapshot:", str(e))
        return None




