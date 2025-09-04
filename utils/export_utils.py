# utils/export_utils.py
from __future__ import annotations
import json, csv
from pathlib import Path
from typing import Any, List, Dict
from fpdf import FPDF
from datetime import datetime

def save_json(obj: Any, path: str | Path) -> bool:
    """Save object as JSON to file."""
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"[export_utils] Error saving to {path}: {e}")
        return False

def generate_daily_csv_report(trades: List[Dict[str, Any]], path: str | Path) -> bool:
    """Save trades list to CSV file."""
    try:
        if not trades:
            print("[export_utils] No trades to export.")
            return False
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=trades[0].keys())
            writer.writeheader()
            writer.writerows(trades)
        return True
    except Exception as e:
        print(f"[export_utils] Error saving CSV: {e}")
        return False

def generate_daily_pdf_report(trades: List[Dict[str, Any]], path: str | Path) -> bool:
    """Save trades list to PDF file."""
    try:
        if not trades:
            print("[export_utils] No trades to export.")
            return False

        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", size=10)
        pdf.cell(200, 10, txt="Daily Trades Report", ln=True, align="C")
        pdf.ln(5)

        headers = list(trades[0].keys())
        col_width = 190 / len(headers)

        for h in headers:
            pdf.cell(col_width, 8, h, border=1)
        pdf.ln(8)

        for t in trades:
            for h in headers:
                pdf.cell(col_width, 8, str(t.get(h, "")), border=1)
            pdf.ln(8)

        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        pdf.output(str(p))
        return True
    except Exception as e:
        print(f"[export_utils] Error saving PDF: {e}")
        return False




