import json
from datetime import datetime
from fpdf import FPDF

PNL_FILE = "pnl_tracker.json"

def update_pnl(symbol, entry, exit_price, direction, leverage, budget):
    try:
        pnl = (exit_price - entry) if direction == "LONG" else (entry - exit_price)
        pnl *= leverage * (budget / entry)

        trade = {
            "symbol": symbol,
            "entry": entry,
            "exit": exit_price,
            "direction": direction,
            "leverage": leverage,
            "budget": budget,
            "pnl": round(pnl, 2),
            "timestamp": datetime.utcnow().isoformat()
        }

        try:
            with open(PNL_FILE, "r") as f:
                data = json.load(f)
        except:
            data = []

        data.append(trade)
        with open(PNL_FILE, "w") as f:
            json.dump(data, f, indent=2)

    except Exception as e:
        print(f"PNL error: {e}")

def generate_pnl_pdf():
    try:
        with open(PNL_FILE, "r") as f:
            trades = json.load(f)
    except:
        trades = []

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.cell(200, 10, txt="PNL Report", ln=True, align='C')

    for t in trades[-20:]:  # רק 20 אחרונים
        line = f"{t['symbol']} | {t['direction']} | Entry: {t['entry']} → Exit: {t['exit']} | PNL: ${t['pnl']}"
        pdf.cell(200, 10, txt=line, ln=True)

    filename = "pnl_report.pdf"
    pdf.output(filename)
    return filename

