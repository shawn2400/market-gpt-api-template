# report_utils.py

import os
import json
import base64
from datetime import datetime
from fpdf import FPDF
import pandas as pd

PNL_FILE = "pnl_tracker.json"
PDF_OUTPUT_PATH = "static/pnl_report.pdf"


def generate_daily_report(as_of_date=None):
    try:
        if not os.path.exists(PNL_FILE):
            raise FileNotFoundError(f"{PNL_FILE} not found.")

        with open(PNL_FILE, "r") as f:
            raw = json.load(f)

        records = []
        for date, trades in raw.items():
            for trade in trades:
                trade["timestamp"] = f"{date}T00:00:00"
                trade.setdefault("success", 1 if trade.get("pnl", 0) > 0 else 0)
                records.append(trade)

        if not records:
            raise ValueError("📭 אין טריידים זמינים בדוח.")

        df = pd.DataFrame(records)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df["date"] = df["timestamp"].dt.date

        grouped = df.groupby("date").agg({
            "pnl": "sum",
            "symbol": "count",
            "success": "mean"
        }).reset_index()

        grouped.columns = ["Date", "Total PNL", "Trades", "Success Rate"]
        grouped["Success Rate"] = (grouped["Success Rate"] * 100).round(2)

        # סינון לפי תאריך אם התקבל
        if as_of_date:
            cutoff = pd.to_datetime(as_of_date).date()
            grouped = grouped[grouped["Date"] <= cutoff]

        if grouped.empty:
            raise ValueError("📭 אין נתונים לתאריך המבוקש.")

        # קביעת כותרת לפי התאריך האחרון המדווח
        report_title_date = grouped["Date"].max() if not grouped.empty else datetime.today().date()

        # יצירת PDF
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", size=12)
        pdf.cell(200, 10, txt=f"📊 Daily Performance Report – {report_title_date}", ln=1, align="C")
        pdf.ln(10)

        for _, row in grouped.iterrows():
            line = f"{row['Date']} | PNL: ${row['Total PNL']:.2f} | Trades: {int(row['Trades'])} | Success: {row['Success Rate']:.2f}%"
            pdf.cell(200, 10, txt=line, ln=1)

        pdf.output(PDF_OUTPUT_PATH)

        with open(PDF_OUTPUT_PATH, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("utf-8")

        return {
            "status": "success",
            "base64_pdf": encoded,
            "summary": grouped.to_dict(orient="records")
        }

    except Exception as e:
        print(f"❌ Error generating report: {e}")
        return {"status": "error", "message": str(e)}







