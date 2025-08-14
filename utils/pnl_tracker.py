# utils/pnl_tracker.py

import json
import os
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP, getcontext
from typing import Dict, Any, List, Optional, Tuple

from fpdf import FPDF

# דיוק חישוב גבוה מספיק לקריפטו
getcontext().prec = 28

# קבצים/נתיבים דיפולטיים
PNL_FILE = os.getenv("PNL_FILE", "pnl_tracker.json")
PDF_OUTPUT_PATH = os.getenv("PNL_PDF_PATH", "static/reports/pnl_report.pdf")

# ---------- Utilities ----------

def _d(x) -> Decimal:
    try:
        return Decimal(str(x))
    except Exception:
        return Decimal(0)

def _round(x: Decimal, ndigits: int = 2) -> Decimal:
    q = Decimal("1." + ("0" * ndigits))
    return x.quantize(q, rounding=ROUND_HALF_UP)

def _ensure_dir_for(path: str) -> None:
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)

def _atomic_write_json(path: str, data: Any) -> None:
    _ensure_dir_for(path)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
    os.replace(tmp, path)

# ---------- Core load/save ----------

def load_pnl() -> Dict[str, List[Dict[str, Any]]]:
    if not os.path.exists(PNL_FILE):
        return {}
    try:
        with open(PNL_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                # נוודא שכל ערך הוא list
                for k, v in list(data.items()):
                    if not isinstance(v, list):
                        data[k] = []
                return data
    except Exception as e:
        print(f"[PNL] ⚠️ שגיאה בקריאת {PNL_FILE}: {e}")
    return {}

def save_pnl(data: Dict[str, List[Dict[str, Any]]]) -> None:
    try:
        _atomic_write_json(PNL_FILE, data)
    except Exception as e:
        print(f"[PNL] ❌ כישלון בכתיבה אטומית ל־{PNL_FILE}: {e}")

# ---------- Business logic ----------

def add_trade(
    data: Dict[str, List[Dict[str, Any]]],
    *,
    symbol: str,
    direction: str,
    entry: float,
    exit_price: float,
    leverage: float,
    qty: float,
    fee_rate: float = 0.0,        # לדוגמה: 0.0004 (0.04%)
    fixed_fee_usdt: float = 0.0   # עמלה קבועה (סה״כ, שתי פקודות)
) -> Tuple[Dict[str, Any], Decimal]:
    """
    מוסיף טרייד למבנה הנתונים ומחזיר (trade_dict, pnl_decimal).
    PnL מחושב: (diff * qty * leverage) - fees
    diff: LONG = (exit - entry), SHORT = (entry - exit)
    fees: (entry * qty + exit * qty) * fee_rate * leverage + fixed_fee_usdt
    """
    symbol = str(symbol).upper().strip()
    d = str(direction or "").upper().strip()
    if d not in ("LONG", "SHORT"):
        d = "LONG"

    entry_d    = _d(entry)
    exit_d     = _d(exit_price)
    lev_d      = _d(leverage)
    qty_d      = _d(qty)
    fee_rate_d = _d(fee_rate)
    fixed_fee_d= _d(fixed_fee_usdt)

    # ולידציה בסיסית
    if entry_d <= 0 or exit_d <= 0 or lev_d <= 0 or qty_d <= 0:
        raise ValueError("entry/exit/leverage/qty must be positive")

    if d == "LONG":
        diff = exit_d - entry_d
    else:
        diff = entry_d - exit_d

    gross_pnl = diff * qty_d * lev_d

    # עמלות: גם על כניסה וגם על יציאה (בקירוב)
    notional_in  = entry_d * qty_d * lev_d
    notional_out = exit_d  * qty_d * lev_d
    fees = (notional_in + notional_out) * fee_rate_d + fixed_fee_d

    net_pnl = gross_pnl - fees

    trade = {
        "symbol": symbol,
        "direction": d,
        "entry": float(_round(entry_d, 6)),
        "exit": float(_round(exit_d, 6)),
        "leverage": float(lev_d),
        "qty": float(_round(qty_d, 6)),
        "pnl": float(_round(net_pnl, 2)),
        "fees": float(_round(fees, 4)),
        "fee_rate": float(fee_rate_d),
        "fixed_fee_usdt": float(_round(fixed_fee_d, 4)),
        "timestamp": datetime.utcnow().isoformat(),
        "success": 1 if net_pnl > 0 else 0,
        "gross_pnl": float(_round(gross_pnl, 2)),
    }
    # מפתח יומי
    today = datetime.utcnow().strftime("%Y-%m-%d")
    data.setdefault(today, []).append(trade)
    return trade, net_pnl

def update_pnl(
    symbol: str,
    direction: str,
    entry: float,
    exit_price: float,
    leverage: float,
    qty: float,
    *,
    fee_rate: float = 0.0,
    fixed_fee_usdt: float = 0.0
) -> float:
    """
    API תואם לאחור: מחזיר PnL (נטו) כ-float.
    """
    data = load_pnl()
    try:
        _, pnl_d = add_trade(
            data,
            symbol=symbol,
            direction=direction,
            entry=entry,
            exit_price=exit_price,
            leverage=leverage,
            qty=qty,
            fee_rate=fee_rate,
            fixed_fee_usdt=fixed_fee_usdt,
        )
        save_pnl(data)
        return float(_round(pnl_d, 2))
    except Exception as e:
        print(f"[PNL] ❌ שגיאה בעדכון PNL: {e}")
        return 0.0

# ---------- Summaries ----------

def daily_summary(data: Optional[Dict[str, List[Dict[str, Any]]]] = None) -> Dict[str, Dict[str, Any]]:
    """
    מחזיר תקציר לכל יום:
    { date: { 'trades': n, 'wins': w, 'losses': l, 'total': X, 'success_rate': Y } }
    """
    data = data if data is not None else load_pnl()
    out: Dict[str, Dict[str, Any]] = {}
    for date, trades in data.items():
        total = Decimal(0)
        wins = 0
        for t in trades:
            pnl = _d(t.get("pnl", 0))
            total += pnl
            if pnl > 0:
                wins += 1
        n = len(trades)
        losses = max(0, n - wins)
        sr = float(_round(Decimal(wins) / Decimal(n) * Decimal(100), 2)) if n else 0.0
        out[date] = {
            "trades": n,
            "wins": wins,
            "losses": losses,
            "total": float(_round(total, 2)),
            "success_rate": sr,
        }
    return out

def overall_summary(data: Optional[Dict[str, List[Dict[str, Any]]]] = None) -> Dict[str, Any]:
    data = data if data is not None else load_pnl()
    n = 0
    wins = 0
    total = Decimal(0)
    for trades in data.values():
        for t in trades:
            pnl = _d(t.get("pnl", 0))
            total += pnl
            n += 1
            if pnl > 0:
                wins += 1
    sr = float(_round(Decimal(wins) / Decimal(n) * Decimal(100), 2)) if n else 0.0
    return {
        "trades": n,
        "wins": wins,
        "losses": max(0, n - wins),
        "total": float(_round(total, 2)),
        "success_rate": sr,
    }

# ---------- PDF report ----------

class _PNLPDF(FPDF):
    def header(self):
        self.set_font("Arial", "B", 14)
        self.cell(0, 10, "Daily PNL Report", border=0, ln=1, align="C")
        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        self.set_font("Arial", "", 10)
        self.cell(0, 6, now, border=0, ln=1, align="C")
        self.ln(2)

    def footer(self):
        self.set_y(-15)
        self.set_font("Arial", "I", 8)
        self.cell(0, 10, f"Page {self.page_no()}", 0, 0, "C")

def generate_pnl_pdf() -> Optional[str]:
    data = load_pnl()
    if not data:
        print("[PNL] אין נתונים לייצוא PDF.")
        return None

    _ensure_dir_for(PDF_OUTPUT_PATH)

    pdf = _PNLPDF()
    pdf.set_auto_page_break(auto=True, margin=12)
    pdf.add_page()

    # סיכום כללי בראש הדו״ח
    ov = overall_summary(data)
    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 8, f"Overall: Trades={ov['trades']} | Wins={ov['wins']} | Losses={ov['losses']} | "
                   f"Total={ov['total']}$ | Success Rate={ov['success_rate']}%", ln=1)
    pdf.ln(2)

    # ימים בסדר יורד
    for date in sorted(data.keys(), reverse=True):
        trades = data[date]
        summary = daily_summary({date: trades})[date]

        # כותרת יום
        pdf.set_font("Arial", "B", 12)
        pdf.cell(0, 8, f"📅 {date} — Trades={summary['trades']} | Total={summary['total']}$ | "
                       f"Success Rate={summary['success_rate']}%", ln=1)
        pdf.set_font("Arial", "", 11)

        # שורות טריידים
        for t in trades:
            pnl = float(_round(_d(t.get("pnl", 0)), 2))
            line = (
                f"{t.get('symbol','?'):>8} | {t.get('direction','?'):>5} | "
                f"Entry: {t.get('entry')} | Exit: {t.get('exit')} | "
                f"Lev: {t.get('leverage')} | Qty: {t.get('qty')} | "
                f"Fees: {t.get('fees', 0)} | PNL: {pnl}$"
            )
            # auto line-break
            pdf.multi_cell(0, 6, line)

        pdf.ln(2)

    try:
        pdf.output(PDF_OUTPUT_PATH)
        return PDF_OUTPUT_PATH
    except Exception as e:
        print(f"[PNL] ❌ שגיאה ביצירת PDF: {e}")
        return None







