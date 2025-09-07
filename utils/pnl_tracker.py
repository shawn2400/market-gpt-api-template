# utils/pnl_tracker.py
from __future__ import annotations
import json, os, tempfile
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
from fpdf import FPDF

PNL_FILE = "pnl_tracker.json"
PDF_OUTPUT_PATH = "static/reports/pnl_report.pdf"

DAILY_HARD_LOSS_USD = float(os.getenv("DAILY_HARD_LOSS_USD", "-150"))

def _atomic_write_json(path: str, data: Any) -> None:
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=d, delete=False, encoding="utf-8") as tmp:
        json.dump(data, tmp, indent=4, ensure_ascii=False)
        tmp.flush(); os.fsync(tmp.fileno()); tmp_name = tmp.name
    os.replace(tmp_name, path)

def _load_json_or_empty(path: str) -> Dict[str, Any]:
    if not os.path.exists(path): return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}

def _to_float(x, default: float = 0.0) -> float:
    try:
        v = float(x)
        if v != v: return default
        return v
    except Exception:
        return default

def update_pnl(symbol: str, direction: str, entry: float, exit_price: float,
               leverage: float, qty: float) -> float:
    today = datetime.utcnow().strftime("%Y-%m-%d")
    data = _load_json_or_empty(PNL_FILE)
    try:
        direction_u = (direction or "").upper()
        entry = _to_float(entry, 0.0); exit_price = _to_float(exit_price, 0.0)
        leverage = _to_float(leverage, 1.0); qty = _to_float(qty, 0.0)
        if entry <= 0 or exit_price <= 0 or qty <= 0 or leverage <= 0:
            raise ValueError("Invalid values")

        diff = (exit_price - entry) if direction_u == "LONG" else (entry - exit_price)
        pnl = round(diff * qty * leverage, 6)

        trade = {
            "symbol": symbol.upper(),
            "direction": direction_u,
            "entry": round(entry, 6),
            "exit": round(exit_price, 6),
            "leverage": leverage,
            "qty": qty,
            "pnl": pnl,
            "timestamp": datetime.utcnow().isoformat(timespec="seconds"),
            "success": 1 if pnl > 0 else 0,
        }
        day_list = data.setdefault(today, [])
        day_list.append(trade)
        _atomic_write_json(PNL_FILE, data)

        # === Check Daily Cap ===
        total_day = sum(_to_float(t.get("pnl")) for t in day_list)
        if total_day <= DAILY_HARD_LOSS_USD:
            os.environ["AUTO_RUN"] = "0"

        return pnl
    except Exception as e:
        print(f"[pnl_tracker] ❌ Error in update_pnl: {e}")
        return 0.0

def _summarize_day(trades: List[Dict[str, Any]]) -> Tuple[float, float]:
    total = sum(_to_float(t.get("pnl"), 0.0) for t in trades)
    wins = sum(1 for t in trades if _to_float(t.get("pnl"), 0.0) > 0)
    rate = (wins / len(trades) * 100.0) if trades else 0.0
    return total, rate

def generate_pnl_pdf(limit_days: Optional[int] = None) -> Optional[str]:
    data = _load_json_or_empty(PNL_FILE)
    if not data: return None
    os.makedirs(os.path.dirname(PDF_OUTPUT_PATH), exist_ok=True)
    dates = sorted(data.keys(), reverse=True)
    if isinstance(limit_days, int) and limit_days > 0: dates = dates[:limit_days]

    pdf = FPDF(); pdf.add_page(); pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_font("Arial", size=16); pdf.cell(0, 10, txt="Daily PnL Report", ln=True, align="C"); pdf.ln(2)

    overall_total = 0.0; overall_trades = 0; overall_wins = 0
    for date in dates:
        trades = list(data.get(date) or [])
        if not trades: continue
        pdf.set_font("Arial", style="B", size=12); pdf.cell(0, 8, txt=f"{date}", ln=True)
        pdf.set_font("Arial", size=11)
        for t in trades:
            pnl = _to_float(t.get("pnl"), 0.0)
            overall_total += pnl; overall_trades += 1; overall_wins += 1 if pnl > 0 else 0
            line = (f"{t.get('symbol','?')} | {t.get('direction','?')} | "
                    f"Entry: {t.get('entry')} | Exit: {t.get('exit')} | "
                    f"Lev: {t.get('leverage')}x | Qty: {t.get('qty')} | PNL: {pnl:.4f}")
            pdf.cell(0, 7, txt=line, ln=True)
        day_total, day_rate = _summarize_day(trades)
        pdf.set_font("Arial", style="B", size=11)
        pdf.cell(0, 7, txt=f"Total: {day_total:.4f} | Success Rate: {day_rate:.2f}%", ln=True); pdf.ln(2)

    overall_rate = (overall_wins / overall_trades * 100.0) if overall_trades else 0.0
    pdf.ln(4); pdf.set_font("Arial", style="B", size=12)
    pdf.cell(0, 8, txt=f"Overall Total: {overall_total:.4f}", ln=True)
    pdf.cell(0, 8, txt=f"Overall Success Rate: {overall_rate:.2f}%", ln=True)
    try:
        pdf.output(PDF_OUTPUT_PATH)
        return PDF_OUTPUT_PATH
    except Exception as e:
        print(f"[pnl_tracker] ❌ Error PDF: {e}")
        return None









