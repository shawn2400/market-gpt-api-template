from __future__ import annotations
import os, httpx

def get_all_futures_usdt_symbols(timeout: float = 8.0):
    """
    Returns a sorted list of all USDT-PERPETUAL futures symbols in TRADING status.
    """
    base = os.getenv("BIN_FAPI_BASE", os.getenv("BINANCE_FAPI", "https://fapi.binance.com")) or "https://fapi.binance.com"
    url  = base.rstrip("/") + "/fapi/v1/exchangeInfo"
    try:
        with httpx.Client(timeout=timeout) as cli:
            r = cli.get(url)
            r.raise_for_status()
            data = r.json()
    except Exception:
        return []
    out = []
    for sym in (data or {}).get("symbols", []):
        if sym.get("status") != "TRADING":
            continue
        if sym.get("contractType") != "PERPETUAL":
            continue
        if sym.get("quoteAsset") != "USDT":
            continue
        s = sym.get("symbol", "")
        if s and s.endswith("USDT"):
            out.append(s)
    return sorted(set(out))
