@router.get("/positions")
async def open_positions(symbol: Optional[str] = Query(None)) -> Dict[str, Any]:
    try:
        return {"ok": True, "positions": futures_open_positions_safe(symbol)}
    except Exception as e:
        logger.error("positions failed: %s", e)
        raise HTTPException(500, str(e))

@router.get("/balance")
async def balance() -> Dict[str, Any]:
    try:
        return {"ok": True, "balances": futures_balance()}
    except Exception as e:
        logger.error("balance failed: %s", e)
        raise HTTPException(500, str(e))

@router.get("/mark-price")
async def mark_price(symbol: str = Query(..., min_length=3)) -> Dict[str, Any]:
    try:
        px = futures_mark_price(symbol)
        if px is None:
            raise RuntimeError("mark price unavailable")
        return {"ok": True, "symbol": symbol.upper(), "markPrice": px}
    except Exception as e:
        logger.error("mark-price failed: %s", e)
        raise HTTPException(500, str(e))

@router.get("/exchange-info")
async def exchange_info() -> Dict[str, Any]:
    try:
        return {"ok": True, "info": futures_exchange_info_safe()}
    except Exception as e:
        logger.error("exchange-info failed: %s", e)
        raise HTTPException(500, str(e))

@router.post("/trade")
async def trade(req: ExecTradeRequest):
    try:
        budget_effective: Optional[float] = None
        if req.budget_usd and req.budget_usd > 0:
            budget_effective = float(req.budget_usd)
        elif req.budget and req.budget > 0:
            budget_effective = float(req.budget)
        args: Dict[str, Any] = {
            "symbol": req.symbol,
            "side": req.side,
            "leverage": req.leverage,
            "dry_run": req.dry_run,
            "entry": req.entry,
            "sl": req.sl,
            "tp": req.tp,
            "tp_targets": req.tp_targets,
            "tp_splits": req.tp_splits,
            "sl_targets": req.sl_targets,
            "sl_splits": req.sl_splits,
            "confirm_first": req.confirm_first,
            "telegram_chat_id": req.telegram_chat_id,
        }
        if budget_effective is not None:
            args["budget"] = budget_effective
        if req.quantity is not None:
            args["quantity"] = req.quantity
        res = await execute_trade_live(**args)
        ok = bool(res and res.get("ok", False))
        status_code = 200 if ok or req.dry_run else 409
        if not ok:
            return JSONResponse({"ok": False, "result": res, "reason": (res or {}).get("reason")}, status_code=status_code)
        return {"ok": True, "result": res}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("trade failed: %s", e)
        raise HTTPException(500, str(e))





























