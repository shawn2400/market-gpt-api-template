# report_utils.py

import os
import base64
from datetime import datetime
from fpdf import FPDF
import pandas as pd

PNL_FILE = "pnl_tracker.json"

def generate_daily_report():
    try:
        if not os.path.exists(PNL_FILE):
            raise FileNotFoundError(f"{PNL_FILE} not found.")

        # קריאה לתוך מבנה נתון
        raw = pd.read_json(PNL_FILE)

        if isinstance(raw, dict):  # אם בפורמט חדש של מילון לפי תאריך
            records = []
            for date, trades in raw.items():
                for trade in trades:
                    trade["timestamp"] = f"{date}T00:00:00"
                    records.append(trade)
            df = pd.DataFrame(records)
        else:
            df = raw

        # עיבוד נתונים
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df["date"] = df["timestamp"].dt.date

        grouped = df.groupby("date").agg({
            "pnl": "sum",
            "symbol": "count",
            "success": "mean"
        }).reset_index()

        grouped.columns = ["Date", "Total PNL", "Trades", "Success Rate"]
        grouped["Success Rate"] = (grouped["Success Rate"] * 100).round(2)

        # יצירת PDF
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", size=12)
        pdf.cell(200, 10, txt="📊 Daily Performance Report", ln=1, align="C")
        pdf.ln(10)

        for _, row in grouped.iterrows():
            date_str = row["Date"].strftime("%Y-%m-%d")
            line = f"{date_str} | PNL: ${row['Total PNL']:.2f} | Trades: {int(row['Trades'])} | Success: {row['Success Rate']:.2f}%"
            pdf.cell(200, 10, txt=line, ln=1)

        output_path = "daily_report.pdf"
        pdf.output(output_path)

        with open(output_path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("utf-8")

        return encoded

    except Exception as e:
        print("❌ Error generating report:", str(e))
        return None





