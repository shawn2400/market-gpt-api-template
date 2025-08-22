# =========================
# Futures Exchange Info cache (with TTL)
# =========================
_futures_exchange_info_cache: Optional[Dict[str, Any]] = None
_valid_futures_symbols: Optional[set[str]] = None
_symbols_last_refresh: float = 0.0
_SYMBOLS_TTL: int = 21600   # 6 שעות = 21600 שניות

def futures_exchange_info_safe(force_refresh: bool = False) -> Dict[str, Any]:
    global _futures_exchange_info_cache, _symbols_last_refresh
    now = time.time()
    if _futures_exchange_info_cache is not None and not force_refresh:
        if now - _symbols_last_refresh < _SYMBOLS_TTL:
            return _futures_exchange_info_cache
    client = get_client()
    info = retry_call(lambda: client.futures_exchange_info(), "futures_exchange_info")
    if isinstance(info, dict):
        _futures_exchange_info_cache = info
        _symbols_last_refresh = now
    return info

def valid_futures_symbols(force_refresh: bool = False) -> set[str]:
    global _valid_futures_symbols
    if _valid_futures_symbols is not None and not force_refresh:
        if time.time() - _symbols_last_refresh < _SYMBOLS_TTL:
            return _valid_futures_symbols
    info = futures_exchange_info_safe(force_refresh=force_refresh)
    symbols = set()
    for s in info.get("symbols", []):
        if s.get("status") == "TRADING":
            symbols.add(s.get("symbol", "").upper())
    _valid_futures_symbols = symbols
    return _valid_futures_symbols

def is_valid_futures_symbol(symbol: str) -> bool:
    return symbol.upper() in valid_futures_symbols()

# =========================
# Futures Mark Price (extended)
# =========================
def futures_mark_price_dict(symbol: str, tries: int = _MAX_RETRIES) -> Dict[str, Any]:
    sym = symbol.upper().strip()

    if not is_valid_futures_symbol(sym):
        raise RuntimeError(f"[Binance] Symbol {sym} is not valid in Futures")

    if PRICE_MONITOR_DISABLE:
        rec = LAST_PRICE_CACHE.get(sym)
        if rec and "price" in rec:
            return {"symbol": sym, "markPrice": str(rec["price"]), "ts": rec.get("ts")}
        raise RuntimeError(f"[Binance] WS/Cache miss for {sym}")

    last_err: Optional[str] = None
    headers = {"Accept": "application/json", "User-Agent": "AlgoGPT-binance-client"}

    for attempt in range(1, tries + 1):
        for base in _BINANCE_FAPI_BASES:
            url = f"{base}/fapi/v1/premiumIndex"
            try:
                with httpx.Client(timeout=_DEFAULT_TIMEOUT, http2=True) as client:
                    r = client.get(url, params={"symbol": sym}, headers=headers)

                if r.status_code == 200:
                    ctype = r.headers.get("Content-Type", "")
                    if ctype.startswith("application/json"):
                        data = r.json()
                        if isinstance(data, dict) and "markPrice" in data:
                            return {
                                "symbol": data.get("symbol", sym),
                                "markPrice": data.get("markPrice"),
                                "fundingRate": data.get("lastFundingRate"),
                                "nextFundingTime": data.get("nextFundingTime"),
                                "ts": int(time.time())
                            }
                        else:
                            last_err = "No markPrice in JSON"
                    else:
                        last_err = f"Invalid content-type {ctype}"
                        level = logging.WARNING if SUPPRESS_BINANCE_WARNINGS else logging.ERROR
                        logger.log(level, f"[Binance] {sym} got non-JSON from {base}")
                        continue
                else:
                    last_err = f"{r.status_code} {r.text[:80]}"
                    level = logging.WARNING if SUPPRESS_BINANCE_WARNINGS else logging.ERROR
                    logger.log(level, f"[Binance] {sym} invalid response from {base}: {last_err}")
            except Exception as e:
                last_err = f"{type(e).__name__}: {e}"
                level = logging.WARNING if SUPPRESS_BINANCE_WARNINGS else logging.ERROR
                logger.log(level, f"[Binance] {sym} exception on {base}: {last_err}")
        time.sleep(0.35 * attempt)

    # ✅ Fallback ל־Cache
    rec = LAST_PRICE_CACHE.get(sym)
    if rec and "price" in rec:
        return {"symbol": sym, "markPrice": str(rec["price"]), "fundingRate": None, "nextFundingTime": None, "ts": rec.get("ts")}

    raise RuntimeError(f"[Binance] futures_mark_price_dict({sym}) failed after {tries} tries: {last_err}")






























































































