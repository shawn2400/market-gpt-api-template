@router.post("/trail")
def place_trailing(
    request: Request,
    payload: Dict[str, Any] = Body(..., example={"symbol": "BTCUSDT", "atr_mult": 1.6}),
    authorization: Optional[str] = Header(None),
    x_timestamp: Optional[str] = Header(None, alias="X-Timestamp"),
    x_nonce: Optional[str] = Header(None, alias="X-Nonce"),
    x_signature: Optional[str] = Header(None, alias="X-Signature"),
) -> Dict[str, Any]:
    if not _auth_ok(authorization):
        raise HTTPException(status_code=401, detail="Unauthorized")

    if _anti_replay_required():
        body = payload
        ok, reason = verify_request(x_timestamp, x_nonce, x_signature, "/position-ops/trail", body, require_signature=True)  # type: ignore
        if not ok:
            raise HTTPException(status_code=401, detail=f"bad_signature: {reason}")

    symbol = (payload.get("symbol") or "").upper().strip()
    atr_mult = payload.get("atr_mult")
    callback_rate = payload.get("callback_rate")
    if not symbol:
        raise HTTPException(status_code=422, detail="missing symbol")

    client, err = _get_client_soft()
    if not client:
        return _ok(skipped=True, reason=err or "no_client")
    _align_position_mode(client)

    try:
        side, qty, entry = _fetch_position_side_qty_entry(client, symbol)
    except HTTPException as e:
        if e.status_code == 409:
            return _ok(skipped=True, reason="no_open_position")
        raise

    # בטל קודם trailing קיים בלבד
    with suppress(Exception):
        _cancel_open_conditional(client, symbol, kinds=("TRAILING_STOP_MARKET",), strict=True)

    # חשב callbackRate (0.1..5.0)
    def _calc_callback_rate() -> float:
        if callback_rate is not None:
            try:
                r = float(callback_rate)
                return max(0.1, min(5.0, r))
            except Exception:
                pass
        if atr_mult is None:
            with suppress(Exception):
                atr_mult_env = float(os.getenv("TRAIL_ATR_MULT", "1.6"))
                return max(0.1, min(5.0, atr_mult_env))
            return 1.6
        try:
            am = float(atr_mult)
        except Exception:
            am = 1.6
        try:
            kl = client.futures_klines(symbol=symbol, interval="1m", limit=50)
            highs = [float(k[2]) for k in kl]
            lows = [float(k[3]) for k in kl]
            closes = [float(k[4]) for k in kl]
            trs: List[float] = []
            for i in range(1, len(kl)):
                h, l, pc = highs[i], lows[i], closes[i - 1]
                tr = max(h - l, abs(h - pc), abs(l - pc))
                trs.append(tr)
            atr = (sum(trs[-14:]) / float(min(14, len(trs)))) if trs else 0.0
            px = _last_price(client, symbol)
            rate = (atr * am / px) * 100.0 if px > 0 else 0.5
            return max(0.1, min(5.0, rate))
        except Exception:
            return 1.6

    cb = round(float(_calc_callback_rate()), 1)

    # ===== כמות נדרשת ב-Binance TRAILING_STOP_MARKET =====
    flt = _get_filters(client, symbol)
    qty_q = _quantize_qty(symbol, qty, flt)
    if qty_q <= 0:
        return _err("place_trailing_failed", detail="non_positive_quantity_after_quantize")

    try:
        client.futures_create_order(
            symbol=symbol,
            side="SELL" if side == "BUY" else "BUY",
            type="TRAILING_STOP_MARKET",
            quantity=qty_q,
            callbackRate=cb,
            reduceOnly=True,
            workingType=os.getenv("BINANCE_WORKING_TYPE", "MARK_PRICE"),
            newClientOrderId=_build_client_order_id(symbol, "SELL" if side == "BUY" else "BUY", role="TRAIL"),
        )
    except Exception as e:
        return _err("place_trailing_failed", detail=str(e))

    _ensure_guard(symbol, prefer_mode="native")
    res = _ok(symbol=symbol, side=side, qty=qty_q, callback_rate=cb)
    _maybe_notify(symbol, "trail", res)
    return res
