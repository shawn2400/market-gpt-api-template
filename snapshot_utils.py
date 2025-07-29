import matplotlib.pyplot as plt
import os
from datetime import datetime


def save_trade_snapshot(trade: dict) -> str | None:
    """
    שומר גרף PNG של טרייד עם קווים ל־Entry, SL, TP, וכיוון,
    בתיקייה static/snapshots. מחזיר את הנתיב לקובץ או None אם נכשל.
    """
    try:
        symbol = trade.get("symbol", "UNKNOWN")
        entry = float(trade.get("entry", 0))
        stop = float(trade.get("stop", 0))
        tp = float(trade.get("tp", 0))
        direction = trade.get("direction", "LONG").upper()
        price_now = float(trade.get("price_now", entry))
        budget = trade.get("budget", None)
        leverage = trade.get("leverage", None)

        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

        # חישוב מרחקים
        range_top = max(entry, tp, price_now)
        range_bottom = min(entry, stop, price_now)
        buffer = (range_top - range_bottom) * 0.3 or entry * 0.02
        y_min = range_bottom - buffer
        y_max = range_top + buffer

        # ציור
        fig, ax = plt.subplots(figsize=(8, 5))
        ax.set_facecolor("white")

        ax.axhline(entry, color="blue", linestyle="--", linewidth=1.5, label=f"Entry: {entry}")
        ax.axhline(stop, color="red", linestyle="--", linewidth=1.5, label=f"Stop: {stop}")
        ax.axhline(tp, color="green", linestyle="--", linewidth=1.5, label=f"TP: {tp}")
        if price_now:
            ax.axhline(price_now, color="orange", linestyle=":", linewidth=1.2, label=f"Now: {price_now}")

        ax.set_ylim([y_min, y_max])
        ax.set_title(f"{symbol} ({direction}) Snapshot", fontsize=14)
        ax.set_xlabel(f"{timestamp}", fontsize=9)
        ax.set_ylabel("Price")
        ax.grid(True, linestyle=":")

        # חץ לכיוון
        arrow_y = entry
        if direction == "LONG":
            ax.annotate("↑ LONG", xy=(0.01, entry), xycoords=("axes fraction", "data"),
                        color="green", fontsize=12, weight="bold")
        else:
            ax.annotate("↓ SHORT", xy=(0.01, entry), xycoords=("axes fraction", "data"),
                        color="red", fontsize=12, weight="bold")

        # טקסט נוסף
        extra = ""
        if budget:
            extra += f"Budget: {budget} USDT  "
        if leverage:
            extra += f"Leverage: {leverage}x"
        if extra:
            ax.text(0.5, 0.02, extra, transform=ax.transAxes, fontsize=9, ha="center")

        ax.legend(loc="upper left", fontsize=8)

        # יצירת תיקייה
        output_dir = "static/snapshots"
        os.makedirs(output_dir, exist_ok=True)

        clean_symbol = symbol.replace("/", "_")
        timestamp_file = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"{output_dir}/{clean_symbol}_{direction}_{timestamp_file}.png"

        # שמירה
        plt.tight_layout()
        plt.savefig(filename)
        plt.close(fig)

        return filename

    except Exception as e:
        print(f"[!] שגיאה בשמירת snapshot: {e}")
        return None








