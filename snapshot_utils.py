import matplotlib.pyplot as plt
import os
from datetime import datetime

def save_trade_snapshot(trade):
    try:
        symbol = trade.get("symbol", "UNKNOWN")
        entry = float(trade.get("entry", 0))
        stop = float(trade.get("stop", 0))
        tp = float(trade.get("tp", 0))
        direction = trade.get("direction", "LONG")
        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H-%M-%S")

        buffer = abs(entry - stop) * 2
        y_min = min(entry, stop, tp) - buffer
        y_max = max(entry, stop, tp) + buffer

        fig, ax = plt.subplots(figsize=(6, 4))
        ax.axhline(entry, color="blue", linestyle="--", label="Entry")
        ax.axhline(stop, color="red", linestyle="--", label="Stop Loss")
        ax.axhline(tp, color="green", linestyle="--", label="Take Profit")

        ax.set_ylim([y_min, y_max])
        ax.set_title(f"{symbol} Trade ({direction})")
        ax.set_xlabel("Time (snapshot)")
        ax.set_ylabel("Price")
        ax.legend()
        ax.grid(True)

        os.makedirs("snapshots", exist_ok=True)
        filename = f"snapshots/{symbol}_{timestamp}.png"
        plt.tight_layout()
        plt.savefig(filename)
        plt.close(fig)

        return filename
    except Exception as e:
        print("❌ Error saving snapshot:", str(e))
        return None




