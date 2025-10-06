# utils/smoke_checks.py
from __future__ import annotations
import os, time, json
from typing import Any, Dict, List
from contextlib import suppress

from utils.guard_stop import ensure_protective_stop

def _get_client():
    from binance.client import Client  # type: ignore
    return Client((os.getenv("BINANCE_API_KEY") or "").strip(), (os.getenv("BINANCE_API_SECRET") or "").strip())

def _open_symbols(cli) -> List[str]:
    out=[]
    with suppress(Exception):
        pos = cli.futures_position_information() or []
        for p in pos:
            sym = str(p.get("symbol") or "").upper()
            amt = float(p.get("positionAmt") or 0.0)
            if abs(amt) > 1e-12:
                out.append(sym)
    if out: return sorted(set(out))
    # fallback to WATCHLIST
    wl = (os.getenv("WATCHLIST","") or "")
    return [s.strip().upper() for s in wl.split(",") if s.strip()]

def _send_telegram(text: str) -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN","").strip()
    chat  = os.getenv("TELEGRAM_CHAT_ID","").strip() or os.getenv("ADMIN_CHAT_ID","").strip()
    if not token or not chat: return
    import requests  # type: ignore
    try:
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      data={"chat_id": chat, "text": text, "parse_mode": "HTML"}, timeout=6)
    except Exception:
        pass

def run_smoke_guard(send_report: bool = True) -> Dict[str, Any]:
    cli = _get_client()
    syms = _open_symbols(cli)
    report = {"ok": True, "checked": [], "fixes": [], "errors": []}
    for s in syms:
        try:
            res = ensure_protective_stop(s)
            report["checked"].append({s: res})
            # דו״ח קצר אם בוצע שינוי מהותי
            if res.get("ok") and any("placed_new_stop" in a for a in res.get("actions",[])):
                report["fixes"].append(s)
        except Exception as e:
            report["ok"] = False
            report["errors"].append({s: str(e)})

    if send_report and (report["fixes"] or report["errors"]):
        msg = "<b>Smoke Guard</b>\n"
        if report["fixes"]:
            msg += "✅ Fixed/Ensured SL: " + ", ".join(report["fixes"]) + "\n"
        if report["errors"]:
            msg += "⚠️ Errors: " + ", ".join(f"{list(e.keys())[0]}: {list(e.values())[0]}" for e in report["errors"]) + "\n"
        _send_telegram(msg)
    return report
