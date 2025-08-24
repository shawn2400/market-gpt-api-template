# routes/binance_status.py
from __future__ import annotations
from fastapi import APIRouter, Depends, Query
from utils.auth import require_api_key
from utils.binance_client import (
    futures_exchange_info_safe,
    valid_futures_symbols,
    futures_mark_price,
)
import os

router = APIRouter(
    # אין prefix כאן – המארח (main.py) מוסיף "/binance"
    dependencies=[Depends(require_api_key)],
    tags=["Binance"],
)

@router.get("/status")
def binance_status():
    """בדיקת סטטוס כוללת מול Binance FAPI + דגימת מחירים."""
    hosts = []
    # חשיפת רשימת hosts מה-ENV (מידע שימושי לדיבוג)
    base = (os.getenv("BINANCE_FAPI_BASE") or "https://fapi1.binance.com").rstrip("/")
    alts = (os.getenv("BINANCE_FAPI_ALTS") or "https://fapi2.binance.com,https://fapi3.binance.com")
    hosts = [base] + [h.strip().rstrip("/") for h in alts.split(",") if h.strip()]

    soft_allow = (os.getenv("BINANCE_SOFT_ALLOW_EXCHANGE_INFO", "1").strip().lower() in ("1","true","yes"))
    testnet = (os.getenv("BINANCE_TESTNET", "false").strip().lower() in ("1","true","yes"))

    # exchangeInfo (עשוי לחזור ריק ב-soft-allow)
    try:
        info = futures_exchange_info_safe()
        ex_info_ok = bool(isinstance(info, dict) and "symbols" in info and len(info.get("symbols", [])) > 0)
    except Exception as e:
        ex_info_ok = False

    # דגימת מחירים
    sample_syms = ["BTCUSDT", "ETHUSDT"]
    samples = {}
    for s in sample_syms:
        try:
            p = futures_mark_price(s)
            samples[s] = p
        except Exception:
            samples[s] = None

    # רשימת סימבולים נסחרים (אם ריק – כנראה WAF + soft-allow)
    try:
        syms = sorted(list(valid_futures_symbols()))[:50]
    except Exception:
        syms = []

    return {
        "hosts": hosts,
        "testnet": testnet,
        "soft_allow_exchange_info": soft_allow,
        "exchange_info_ok": ex_info_ok,
        "mark_price_samples": samples,
        "trading_symbols_preview": syms,
    }

@router.get("/mark-price")
def get_mark_price(symbol: str = Query(..., min_length=3, description="e.g. BTCUSDT")):
    """מחזיר Mark Price לסימבול ספציפי."""
    price = futures_mark_price(symbol)
    return {"symbol": symbol.upper(), "price": price}

@router.get("/exchange-symbols")
def get_exchange_symbols():
    """רשימת סימבולים (TRADING) מתוך exchangeInfo (עשוי להיות ריק ב-soft-allow)."""
    try:
        syms = sorted(list(valid_futures_symbols()))
    except Exception:
        syms = []
    return {"count": len(syms), "symbols": syms}
