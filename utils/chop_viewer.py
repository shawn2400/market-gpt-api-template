# utils/chop_viewer.py
from __future__ import annotations
import pandas as pd
import matplotlib.pyplot as plt
from utils.chop_zones import detect_chop_zones

def plot_chop_zones(df: pd.DataFrame, adx_col: str = "adx", price_col: str = "close") -> None:
    """
    תצוגה גרפית של אזורי Chop על־גבי גרף המחיר.
    """
    if df is None or df.empty or price_col not in df or adx_col not in df:
        print("Invalid input data")
        return

    zones = detect_chop_zones(df, adx_col=adx_col)
    plt.figure(figsize=(14, 6))
    plt.plot(df[price_col].values, label="Price", color="blue")

    for start, end in zones:
        plt.axvspan(start, end, color="red", alpha=0.3)

    plt.title("Chop Zones")
    plt.xlabel("Bar Index")
    plt.ylabel(price_col.capitalize())
    plt.legend()
    plt.tight_layout()
    plt.show()

