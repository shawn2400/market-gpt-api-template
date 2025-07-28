import matplotlib.pyplot as plt
import os
from datetime import datetime

def save_trade_snapshot(trade):
    try:
        symbol = trade.get("symbol", "UNKNOWN")
        entry = float(trade.get("entry", 0))
        stop = float(trade.get("stop", 0))
        tp = float(trade.get("tp", 0))
        direction = trade.get("direction", "LONG").upper()
        timestamp = datetime.utcnow().strftime("%Y-%m-%d_%H-%M-%S")

        # חישוב גבולות הגרף עם buffer
        buffer = max(abs(entry - stop), abs(tp - entry)) * 1.5
        y_min = min(entry, stop, tp) - buffer
        y_max = max(entry, stop, tp) + buffer

        fig, ax = plt.subplots(figsize=(7, 4))
        ax.axhline(entry, color="blue", linestyle="--", label=f"Entry: {entry}")
        ax.axhline(stop, color="red", linestyle="--", label=f"Stop: {stop}")
        ax.axhline(tp, color="green", linestyle="--", label=f"TP: {tp}")

        ax.set_ylim([y_min, y_max])
        ax.set_title(f"{symbol} Trade Snapshot ({direction})")
        ax.set_xlabel("Snapshot Time")
        ax.set_ylabel("Price")
        ax.legend()
        ax.grid(True)

        os.makedirs("snapshots", exist_ok=True)
        filename = f"snapshots/{symbol}_{direction}_{timestamp}.png"
        plt.tight_layout()
        plt.savefig(filename)
        plt.close(fig)

        return filename

    except Exception as e:
        print(f"[!] שגיאה בשמירת Snapshot: {e}")
        return None






