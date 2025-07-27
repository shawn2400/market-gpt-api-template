import os
import json
from fpdf import FPDF
from datetime import datetime

def generate_daily_report():
    folder = "snapshots"
    if not os.path.exists(folder):
        return None

    report_path = os.path.join(folder, f"daily_report_{datetime.now().strftime('%Y%m%d')}.pdf")
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.cell(200, 10, txt="Daily Trade Report", ln=1, align="C")

    files = sorted(os.listdir(folder))[-10:]  # take last 10 snapshots
    for fname in files:
        path = os.path.join(folder, fname)
        try:
            with open(path, "r") as f:
                trade = json.load(f)
                pdf.ln(5)
                for key, value in trade.items():
                    pdf.cell(200, 10, txt=f"{key}: {value}", ln=1)
        except:
            continue

    pdf.output(report_path)
    return report_path


