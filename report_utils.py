import json
import os
import base64
from datetime import datetime
from fpdf import FPDF
import pandas as pd

def generate_daily_report():
    try:
        if not os.path.exists("pnl_tracker.json"):
            raise FileNotFoundError("pnl_tracker.json not found.")

        df = pd.read_json("pnl_tracker.json")
        df["date"] = pd.to_datetime(df["timestamp"]).dt.date
        grouped = df.groupby("date").agg({
            "pnl": ["sum", "count"],
            "success": "mean"
        }).reset_index()
        grouped.columns = ["Date", "Total PNL", "Trades", "Success Rate"]
        grouped["Success Rate"] = (grouped["Success Rate"] * 100).round(2)

        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", size=12)
        pdf.cell(200, 10, txt="Daily Performance Report", ln=1, align="C")
        pdf.ln(10)

        for i in range(len(grouped)):
            row = grouped.iloc[i]
            pdf.cell(200, 10, txt=f"{row['Date']} - PNL: ${row['Total PNL']}, Trades: {row['Trades']}, Success Rate: {row['Success Rate']}%", ln=1)

        output_path = "daily_report.pdf"
        pdf.output(output_path)

        with open(output_path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("utf-8")
        return encoded
    except Exception as e:
        print("Error generating report:", str(e))
        return None



