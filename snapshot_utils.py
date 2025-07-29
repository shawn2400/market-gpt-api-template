import matplotlib.pyplot as plt
import os
from datetime import datetime


def save_trade_snapshot(trade: dict) -> str | None:
    """
    שומר גרף PNG של טרייד עם קווים ל־Entry, Stop, TP (ולעיתים גם מחיר נוכחי),
    בתיקייה static/snapshots. מחזיר את הנתיב לקובץ או None אם נכשלה שמירה.
    """
    try:
        symbol = trade.get("symbol", "UNKNOWN")
        entry = float(trade.get("entry", 0))
        stop = float(trade.get("stop", 0))
        tp = float(trade.get("tp", 0))
        direction = trade.get("direction", "LONG").upper()
        price_now = float(trade.get("price_now", 0)) if "price_now" in trade else None
        timestamp = datetime.utcnow().strftime("%Y-%m-%d_%H-%M-%S")

        # חישוב גבולות גרף עם buffer
        buffer = max(abs(entry - stop), abs(tp - entry)) * 1.5 or entry * 0.02
        y_min = min(entry, stop, tp, price_now if price_now else entry) - buffer
        y_max = max(entry, stop, tp, price_now if price_now else entry) + buffer

        # ציור גרף
        fig, ax = plt.subplots(figsize=(7, 4))
        ax.axhline(entry, color="blue", linestyle="--", linewidth=1.5, label=f"Entry: {entry}")
        ax.axhline(stop, color="red", linestyle="--", linewidth=1.5, label=f"Stop: {stop}")
        ax.axhline(tp, color="green", linestyle="--", linewidth=1.5, label=f"TP: {tp}")
        if price_now:
            ax.axhline(price_now, color="orange", linestyle=":", linewidth=1.5, label=f"Price Now: {price_now}")

        ax.set_ylim([y_min, y_max])
        ax.set_title(f"{symbol} Trade Snapshot ({direction})", fontsize=12)
        ax.set_xlabel("Snapshot Time")
        ax.set_ylabel("Price")
        ax.legend()
        ax.grid(True)

        # תיקייה ל־snapshots
        output_dir = "static/snapshots"
        os.makedirs(output_dir, exist_ok=True)
        filename = f"{output_dir}/{symbol}_{direction}_{timestamp}.png"

        # שמירה
        plt.tight_layout()
        plt.savefig(filename)
        plt.close(fig)

        return filename

    except Exception as e:
        print(f"[!] Snapshot Save Error: {e}")
        return None








