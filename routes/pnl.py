# routes/pnl.py
from __future__ import annotations
import os
from typing import Dict, Any
from fastapi import APIRouter, Body, HTTPException, Depends

from utils import pnl_tracker
from utils.auth import require_bearer_token

router = APIRouter(prefix="/pnl", tags=["PnL"], dependencies=[Depends(require_bearer_token)])

@router.post("/update", summary="Update PnL from a trade", operation_id="postPnlUpdate")
async def post_pnl_update(
    payload: Dict[str, Any] = Body(
        ...,
        example={
            "symbol": "BTCUSDT",
            "direction": "LONG",
            "entry": 64000,
            "exit_price": 65000,
            "leverage": 10,
            "qty": 0.01,
        },
    )
) -> Dict[str, Any]:
    try:
        pnl = pnl_tracker.update_pnl(
            symbol=payload["symbol"],
            direction=payload["direction"],
            entry=payload["entry"],
            exit_price=payload["exit_price"],
            leverage=payload.get("leverage", 1.0),
            qty=payload["qty"],
        )
        return {"ok": True, "pnl": pnl}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"pnl error: {e}")

@router.get("/daily", summary="Get daily PnL summary", operation_id="getPnlDaily")
async def get_pnl_daily() -> Dict[str, Any]:
    try:
        from datetime import datetime
        data = pnl_tracker._load_json_or_empty(pnl_tracker.PNL_FILE)
        today = datetime.utcnow().strftime("%Y-%m-%d")
        trades = data.get(today, [])
        total, rate = pnl_tracker._summarize_day(trades)
        return {"ok": True, "date": today, "total": total, "success_rate": rate, "trades": trades}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"pnl summary error: {e}")

@router.get("/report", summary="Generate PnL PDF report", operation_id="getPnlReport")
async def get_pnl_report(limit_days: int = 7) -> Dict[str, Any]:
    try:
        pdf_path = pnl_tracker.generate_pnl_pdf(limit_days=limit_days)
        if not pdf_path:
            return {"ok": False, "note": "no trades found"}
        base = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
        url = f"{base}/{pdf_path}" if base else f"/{pdf_path}"
        return {"ok": True, "file_path": pdf_path, "url": url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"pnl pdf error: {e}")


