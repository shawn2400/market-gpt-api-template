import json
import os
from datetime import datetime
from fpdf import FPDF

PNL_FILE = "pnl_tracker.json"

def update_pnl(symbol, pnl):
    today = datetime.now().strftime("%Y-%m-%d")
    if not os.path.exists(PNL_FILE):
        data = {}
    else:
        with open(PNL_FILE, "r") as f:
            data = json.load(f)

    if today not in data:
        data[today] = []

    data[today].append({"symbol": symbol, "pnl": pnl})

    with open(PNL_FILE, "w") as f:
        json.dump(data, f, indent=4)

def generate_pnl_pdf():
    if not os.path.exists(PNL_FILE):
        return None

    with open(PNL_FILE, "r") as f:
        data = json.load(f)

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=14)
    pdf.cell(200, 10, txt="Daily PNL Report", ln=True, align="C")

    for date, trades in data.items():
        pdf.ln(10)
        pdf.set_font("Arial", size=12)
        pdf.cell(200, 10, txt=f"📅 {date}", ln=True, align="L")
        total = 0
        for t in trades:
            line = f"{t['symbol']} | PNL: {t['pnl']}$"
            pdf.cell(200, 8, txt=line, ln=True, align="L")
            total += t['pnl']
        pdf.cell(200, 8, txt=f"📈 Total: {round(total,2)}$", ln=True, align="L")

    output_path = "/app/static/pnl_report.pdf"
    pdf.output(output_path)
    return output_path




