# utils/pnl_tracker.py

import json
import os
from datetime import datetime
from fpdf import FPDF

PNL_FILE = "pnl_tracker.json"
PDF_OUTPUT_PATH = "static/pnl_report.pdf"  # מותאם לכל מערכת

def update_pnl(symbol, direction, entry, exit_price, leverage, qty):
    today = datetime.now().strftime("%Y-%m-%d")
    data = {}

    try:
        if os.path.exists(PNL_FILE):
            with open(PNL_FILE, "r") as f:
                data = json.load(f)
    except Exception as e:
        print(f"[!] שגיאה בקריאת קובץ PNL: {e}")
        data = {}

    if today not in data:
        data[today] = []

    try:
        diff = (exit_price - entry) if direction.upper() == "LONG" else (entry - exit_price)
        pnl = round(diff * qty * leverage, 2)

        data[today].append({
            "symbol": symbol,
            "direction": direction.upper(),
            "entry": entry,
            "exit": exit_price,
            "leverage": leverage,
            "qty": qty,
            "pnl": pnl
        })

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
        print(f"[!] שגיאה בקריאת קובץ PNL ל־PDF: {e}")
        return None

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=14)
    pdf.cell(200, 10, txt="📊 Daily PNL Report", ln=True, align="C")

    for date, trades in sorted(data.items(), reverse=True):
        pdf.ln(8)
        pdf.set_font("Arial", size=12)
        pdf.cell(200, 8, txt=f"📅 {date}", ln=True, align="L")
        total = 0

        for t in trades:
            line = f"{t['symbol']} | {t['direction']} | Entry: {t['entry']} | Exit: {t['exit']} | PNL: {t['pnl']}$"
            pdf.cell(200, 8, txt=line, ln=True, align="L")
            total += t['pnl']

        pdf.set_font("Arial", "B", size=12)
        pdf.cell(200, 8, txt=f"Total: {round(total, 2)}$", ln=True, align="L")

    try:
        pdf.output(PDF_OUTPUT_PATH)
        return PDF_OUTPUT_PATH
    except Exception as e:
        print(f"[!] שגיאה ביצירת PDF: {e}")
        return None






