# utils/snapshot_utils.py
from __future__ import annotations

import os
from datetime import datetime

# חשוב לשרתים ללא תצוגה (Docker/Render)
import matplotlib
matplotlib.use("Agg")  # אין GUI
import matplotlib.pyplot as plt


def _to_float(x, default: float = 0.0) -> float:
    try:
        v = float(x)
        if v != v:  # NaN
            return default
        return v
    except Exception:
        return default


def save_trade_snapshot(trade: dict) -> str | None:
    """
    שומר גרף PNG של טרייד עם קווי Entry/SL/TP/Now + פרטים (כיוון/לבס/תקציב/איכות).
    נשמר תחת static/snapshots.
    :return: נתיב הקובץ (str) או None אם נכשל.
    """
    try:
        symbol = str(trade.get("symbol") or "UNKNOWN").upper()
        direction = str(trade.get("direction") or "LONG").upper()

        entry = _to_float(trade.get("entry"), 0.0)
        stop = _to_float(trade.get("stop"), 0.0)
        tp = _to_float(trade.get("tp"), 0.0)
        price_now = _to_float(trade.get("price_now"), entry if entry > 0 else 0.0)

        budget = trade.get("budget", None)
        leverage = trade.get("leverage", None)
        quality_score = trade.get("quality_score", None)

        # בלי ערכי בסיס — אין מה לשרטט
        if entry <= 0 or stop <= 0 or tp <= 0:
            raise ValueError("entry/stop/tp must be positive numbers")

        timestamp_human = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

        # טווח Y עם buffer סביר, גם כשערכים כמעט זהים
        range_top = max(entry, tp, price_now)
        range_bottom = min(entry, stop, price_now)
        raw_span = max(1e-9, (range_top - range_bottom))
        buffer = max(raw_span * 0.30, entry * 0.01)  # מינ' 1%
        y_min = max(0.0, range_bottom - buffer)
        y_max = range_top + buffer

        fig, ax = plt.subplots(figsize=(8, 5))
        ax.set_facecolor("white")

        def _fmt(v: float) -> str:
            # פורמט ידידותי: שלמות או עד 6 ספרות אחרי הנקודה
            return f"{v:.6f}".rstrip("0").rstrip(".")

        # צבעים עקביים:
        # Entry = כחול, Stop = אדום, TP = ירוק, Now = כתום
        ax.axhline(entry, linestyle="--", linewidth=1.8, color="#1f77b4", label=f"Entry: {_fmt(entry)}")
        ax.axhline(stop,  linestyle="--", linewidth=1.8, color="#d62728", label=f"Stop: {_fmt(stop)}")
        ax.axhline(tp,    linestyle="--", linewidth=1.8, color="#2ca02c", label=f"TP: {_fmt(tp)}")
        if price_now > 0:
            ax.axhline(price_now, linestyle=":", linewidth=1.6, color="#ff7f0e", label=f"Now: {_fmt(price_now)}")

        ax.set_ylim([y_min, y_max])
        ax.set_title(f"{symbol} ({direction}) — Trade Snapshot", fontsize=14)
        ax.set_xlabel(timestamp_human, fontsize=9)
        ax.set_ylabel("Price", fontsize=11)
        ax.grid(True, linestyle=":")

        # אין ציר X (זה Snapshot נקודתי)
        plt.xticks([])

        # חץ קטן המציין כיוון
        if direction == "LONG":
            ax.annotate("↑ LONG", xy=(0.01, entry), xycoords=("axes fraction", "data"),
                        fontsize=12, weight="bold", color="#1f77b4")
        else:
            ax.annotate("↓ SHORT", xy=(0.01, entry), xycoords=("axes fraction", "data"),
                        fontsize=12, weight="bold", color="#d62728")

        # טקסט נתוני עזר
        extras = []
        if budget is not None:
            extras.append(f"Budget: {budget}")
        if leverage is not None:
            extras.append(f"Leverage: {leverage}x")
        if quality_score is not None:
            extras.append(f"QS: {quality_score}/10")

        if extras:
            ax.text(0.5, 0.02, "  |  ".join(map(str, extras)),
                    transform=ax.transAxes, fontsize=9, ha="center")

        ax.legend(loc="upper left", fontsize=8)

        output_dir = "static/snapshots"
        os.makedirs(output_dir, exist_ok=True)

        clean_symbol = symbol.replace("/", "_")
        ts_file = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = os.path.join(output_dir, f"{clean_symbol}_{direction}_{ts_file}.png")

        plt.tight_layout()
        plt.savefig(filename, dpi=150)
        plt.close(fig)

        return filename

    except Exception as e:
        print(f"[snapshot_utils] ❌ שגיאה בשמירת snapshot: {e}")
        try:
            plt.close("all")
        except Exception:
            pass
        return None


# תאימות לשמות קודמים
generate_trade_snapshot = save_trade_snapshot











