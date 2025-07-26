import matplotlib.pyplot as plt
import pandas as pd
import os
from datetime import datetime

def generate_trade_snapshot(symbol, prices, entry, stop, tp, direction):
    df = pd.DataFrame(prices)
    df.index = range(len(df))

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(df['close'], label='Close Price', linewidth=2)

    # קווים עבור Entry / SL / TP
    ax.axhline(entry, color='blue', linestyle='--', label='Entry')
    ax.axhline(stop, color='red', linestyle='--', label='Stop Loss')
    ax.axhline(tp, color='green', linestyle='--', label='Take Profit')

    # כיוון LONG/SHORT
    ax.set_title(f"{symbol} - {direction}", fontsize=14)
    ax.set_xlabel("Index")
    ax.set_ylabel("Price")
    ax.legend()

    # יצירת שם קובץ ייחודי
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"snapshot_{symbol}_{timestamp}.png"
    output_path = os.path.join("snapshots", filename)

    # יצירת תיקיית snapshots אם לא קיימת
    os.makedirs("snapshots", exist_ok=True)

    # שמירת גרף
    plt.tight_layout()
    plt.savefig(output_path)
    plt.close()

    return output_path

