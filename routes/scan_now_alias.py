# routes/scan_now_alias.py
from __future__ import annotations
from fastapi import APIRouter, Query, HTTPException
from typing import List, Optional, Dict, Any
import os, httpx

# נסה לייבא scan_symbols; אם בקוד שלך הפונקציה נקראת run_scan – ניצור אליאס
try:
    from routes.scan import scan_symbols, ScanResponse
except Exception:
    from routes.scan import run_scan as scan_symbols, ScanResponse  # type: ignore

router = APIRouter(tags=["ScanNow"], prefix="")

PUBLIC_HOST = os.getenv("PUBLIC_HOST", "").rstrip("/")
ALERTS_ANALYSIS_URL = os.getenv("ALERTS_ANALYSIS_URL", f"{PUBLIC_HOST}/alerts/analysis").strip()
API_TOKEN = os.getenv("API_TOKEN", os.getenv("PRIMARY_API_TOKEN", "")).strip()

# מקור ברירת־מחדל לסימבולים
WATCHLIST = [s.strip().upper() for s in os.getenv("WATCHLIST", "BTCUSDT,ETHUSDT,SOLUSDT").split(",") if s.strip()]

async def _get_top_volume_symbols(host: str, headers: Dict[str, str]) -> List[str]:
    url = f"{host}/scan/top-volume"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(url, headers=headers)
            r.raise_for_status()
            data = r.json()
            # מצפה לשדה "symbols" או רשימת {symbol: "..."}
            if isinstance(data, dict) and "symbols" in data:
                syms = data["symbols"]
                if isinstance(syms, list):
                    return [str(x).upper() for x in syms]
            if isinstance(data, list):
                out = []
                for row in data:
                    sym = (row.get("symbol") if isinstance(row, dict) else str(row)).upper()
                    out.append(sym)
                return out
    except Exception:
        pass
    return []

async def _post_to_analysis(url: str, payload: Dict[str, Any], headers: Dict[str, str]) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.post(url, json=payload, headers=headers)
        r.raise_for_status()
        return r.json()

def _auth_headers() -> Dict[str, str]:
    h = {"Accept": "application/json"}
    if API_TOKEN:
        h["x-api-key"] = API_TOKEN
    return h

@router.get("/scan/now", summary="Run immediate scan and push candidates to Telegram")
async def scan_now(
    interval: str = Query("15m"),
    limit: int = Query(200, ge=50, le=200),
    max_symbols: int = Query(30, ge=1, le=200),
    host: Optional[str] = Query(None, description="override public host (debug)"),
) -> Dict[str, Any]:
    """
    1) משיג רשימת סימבולים מ-/scan/top-volume (או WATCHLIST).
    2) מחשב אינדיקטורים/ציון דרך scan_symbols (routes/scan.py).
    3) משגר את הסיגנלים ל-/alerts/analysis כדי ליצור Approval בטלגרם.
    """
    public_host = (host or PUBLIC_HOST or "").rstrip("/")
    if not public_host:
        raise HTTPException(500, "PUBLIC_HOST is not set")

    headers = _auth_headers()

    # שלב א: אסוף סימבולים
    syms = await _get_top_volume_symbols(public_host, headers=headers)
    if not syms:
        syms = WATCHLIST[:]  # fallback
    syms = [s for s in syms if s and s.endswith("USDT")]
    syms = syms[:max_symbols]

    if not syms:
        raise HTTPException(400, "No symbols to scan")

    # שלב ב: הפעל את הסורק הקיים (routes/scan.py)
    # נשתמש בפונקציה פנימית לאסוף response_model זהה
    scan_resp: ScanResponse = await scan_symbols(symbols=syms, interval=interval, limit=limit)  # type: ignore

    # שלב ג: שלח לניתוח/הצעה (alerts/analysis) – כאן מתבצרת הזרקת ההצעות לטלגרם
    payload = {
        "ok": scan_resp.ok,
        "count_total": scan_resp.count_total,
        "returned": scan_resp.returned,
        # נשלח מבנה פשוט: [ {symbol, interval, indicators:{...}} ... ]
        "signals": [
            {
                "symbol": s.symbol,
                "interval": s.interval,
                "indicators": (s.indicators.dict() if hasattr(s.indicators, "dict") else None),
            }
            for s in (scan_resp.signals or [])
            if getattr(s, "ok", True)
        ],
        "source": "scan_now",
    }

    try:
        analysis_rsp = await _post_to_analysis(ALERTS_ANALYSIS_URL, payload, headers)
    except Exception as e:
        # עדיין נחזיר את תוצאת הסריקה, כדי שתוכל לראות מה יצא
        return {
            "ok": False,
            "error": f"analysis_post_failed: {e}",
            "public_host": public_host,
            "sent_to": ALERTS_ANALYSIS_URL,
            "scan": payload,
        }

    return {
        "ok": True,
        "public_host": public_host,
        "sent_to": ALERTS_ANALYSIS_URL,
        "analysis_result": analysis_rsp,
        "scanned": len(syms),
        "interval": interval,
    }


