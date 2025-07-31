# === snapshot_utils.py ===
import matplotlib.pyplot as plt
import os
from datetime import datetime

def save_trade_snapshot(trade: dict) -> str | None:
    """
    שומר גרף PNG של טרייד עם קווים ל־Entry, SL, TP, מחיר נוכחי, וכיוון.
    בתיקייה static/snapshots.
    מחזיר את הנתיב לקובץ או None אם נכשל.
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
        quality_score = trade.get("quality_score", None)

        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

        range_top = max(entry, tp, price_now)
        range_bottom = min(entry, stop, price_now)
        buffer = (range_top - range_bottom) * 0.3 or entry * 0.02
        y_min = max(range_bottom - buffer, 0)
        y_max = range_top + buffer

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
        plt.xticks([])  # הסתרת ציר X

        if direction == "LONG":
            ax.annotate("↑ LONG", xy=(0.01, entry), xycoords=("axes fraction", "data"),
                        color="green", fontsize=12, weight="bold")
        else:
            ax.annotate("↓ SHORT", xy=(0.01, entry), xycoords=("axes fraction", "data"),
                        color="red", fontsize=12, weight="bold")

        extras = []
        if budget:
            extras.append(f"Budget: {budget} USDT")
        if leverage:
            extras.append(f"Leverage: {leverage}x")
        if quality_score is not None:
            extras.append(f"QS: {quality_score}/10")
        if extras:
            ax.text(0.5, 0.02, "  |  ".join(extras), transform=ax.transAxes,
                    fontsize=9, ha="center", color="gray")

        ax.legend(loc="upper left", fontsize=8)

        output_dir = "static/snapshots"
        os.makedirs(output_dir, exist_ok=True)

        clean_symbol = symbol.replace("/", "_")
        timestamp_file = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"{output_dir}/{clean_symbol}_{direction}_{timestamp_file}.png"

        plt.tight_layout()
        plt.savefig(filename)
        plt.close(fig)

        return filename

    except Exception as e:
        print(f"[!] שגיאה בשמירת snapshot: {e}")
        return None

# תואם לגרסאות קודמות
generate_trade_snapshot = save_trade_snapshot


# === pnl_tracker.py ===
import json
import os
from datetime import datetime
from fpdf import FPDF

PNL_FILE = "pnl_tracker.json"
PDF_OUTPUT_PATH = "static/reports/pnl_report.pdf"

# יצירת קובץ ריק אם לא קיים
if not os.path.exists(PNL_FILE):
    with open(PNL_FILE, "w") as f:
        json.dump({}, f)

def update_pnl(symbol, direction, entry, exit_price, leverage, qty):
    today = datetime.utcnow().strftime("%Y-%m-%d")
    data = {}

    try:
        with open(PNL_FILE, "r") as f:
            data = json.load(f)
    except Exception as e:
        print(f"[!] שגיאה בקריאת PNL: {e}")
        data = {}

    if today not in data:
        data[today] = []

    try:
        diff = (exit_price - entry) if direction.upper() == "LONG" else (entry - exit_price)
        pnl = round(diff * qty * leverage, 2)

        trade = {
            "symbol": symbol,
            "direction": direction.upper(),
            "entry": round(entry, 4),
            "exit": round(exit_price, 4),
            "leverage": leverage,
            "qty": qty,
            "pnl": pnl,
            "timestamp": datetime.utcnow().isoformat(),
            "success": 1 if pnl > 0 else 0
        }

        data[today].append(trade)

        with open(PNL_FILE, "w") as f:
            json.dump(data, f, indent=4)

        return pnl
    except Exception as e:
        print(f"[!] שגיאה בחישוב או כתיבה של PNL: {e}")
        return 0

def generate_pnl_pdf():
    if not os.path.exists(PNL_FILE):
        return None

    try:
        with open(PNL_FILE, "r") as f:
            data = json.load(f)
    except Exception as e:
        print(f"[!] שגיאה בקריאת PNL לְ‏PDF: {e}")
        return None

    os.makedirs("static/reports", exist_ok=True)
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=14)
    pdf.cell(200, 10, txt="📊 Daily PNL Report", ln=True, align="C")

    for date, trades in sorted(data.items(), reverse=True):
        pdf.ln(8)
        pdf.set_font("Arial", size=12)
        pdf.cell(200, 8, txt=f"🗕️ {date}", ln=True, align="L")
        total = 0
        wins = 0

        for t in trades:
            pnl = round(t['pnl'], 2)
            total += pnl
            wins += 1 if pnl > 0 else 0
            line = f"{t['symbol']} | {t['direction']} | Entry: {t['entry']} | Exit: {t['exit']} | PNL: {pnl}$"
            pdf.cell(200, 8, txt=line, ln=True, align="L")

        success_rate = round((wins / len(trades)) * 100, 2) if trades else 0
        pdf.set_font("Arial", "B", size=12)
        pdf.cell(200, 8, txt=f"Total: {total}$ | Success Rate: {success_rate}%", ln=True, align="L")

    try:
        pdf.output(PDF_OUTPUT_PATH)
        return PDF_OUTPUT_PATH
    except Exception as e:
        print(f"[!] שגיאה ביצירת PDF: {e}")
        return None









