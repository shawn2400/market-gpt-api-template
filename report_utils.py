from fpdf import FPDF
import json
import matplotlib.pyplot as plt
import os
from datetime import datetime

def generate_daily_report(pnl_file='pnl_tracker.json', output_file='daily_report.pdf'):
    # קריאת נתוני PNL
    if not os.path.exists(pnl_file):
        return None

    with open(pnl_file, 'r') as f:
        pnl_data = json.load(f)

    if not pnl_data:
        return None

    # יצירת גרף רווח יומי
    dates = [entry['date'] for entry in pnl_data]
    pnls = [entry['pnl'] for entry in pnl_data]

    plt.figure(figsize=(8, 4))
    plt.plot(dates, pnls, marker='o', linestyle='-', color='blue')
    plt.xticks(rotation=45)
    plt.xlabel('Date')
    plt.ylabel('Daily PNL ($)')
    plt.title('Daily Profit & Loss')
    plt.tight_layout()
    graph_path = 'pnl_graph.png'
    plt.savefig(graph_path)
    plt.close()

    # יצירת דוח PDF
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(0, 10, 'Daily Trading Report', ln=True, align='C')

    pdf.set_font("Arial", size=12)
    total_trades = len(pnl_data)
    profitable = sum(1 for entry in pnl_data if entry['pnl'] > 0)
    win_rate = round((profitable / total_trades) * 100, 2)
    total_pnl = sum(pnls)

    pdf.ln(10)
    pdf.cell(0, 10, f'Total Trades: {total_trades}', ln=True)
    pdf.cell(0, 10, f'Profitable Trades: {profitable}', ln=True)
    pdf.cell(0, 10, f'Win Rate: {win_rate}%', ln=True)
    pdf.cell(0, 10, f'Total PNL: ${total_pnl:.2f}', ln=True)

    today = datetime.now().strftime('%Y-%m-%d')
    today_data = next((entry for entry in pnl_data if entry['date'] == today), None)
    if today_data:
        pdf.cell(0, 10, f"Today's PNL: ${today_data['pnl']:.2f}", ln=True)

    pdf.ln(10)
    pdf.cell(0, 10, 'PNL Graph:', ln=True)
    pdf.image(graph_path, x=10, y=pdf.get_y(), w=190)

    pdf.output(output_file)

    # המרה ל־base64 אם רוצים לשלב ב־API
    with open(output_file, 'rb') as f:
        pdf_bytes = f.read()
    return pdf_bytes

