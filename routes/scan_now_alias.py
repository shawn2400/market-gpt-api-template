# routes/scan_now_alias.py
from __future__ import annotations
from fastapi import APIRouter, Depends, Query, Request
from typing import Optional, Dict, Any, List
import os

try:
    from utils.auth import require_bearer_token  # type: ignore
except Exception:
    def require_bearer_token():
        return None

router = APIRouter(prefix="/scan", tags=["Scanner"], dependencies=[Depends(require_bearer_token)])

# --- מקור הסריקה ---
try:
    from routes.scan_top_volume import scan_top_volume  # type: ignore
except Exception:
    scan_top_volume = None  # type: ignore

# --- שליחה לטלגרם: ננסה notifier, ואם אין – API ישיר ---
_send_text = None
_send_message = None
try:
    from utils.telegram_notifier import send_text  # type: ignore
    _send_text = send_text
except Exception:
    pass
try:
    from utils.telegram_notifier import send_message  # type: ignore
    _send_message = send_message
except Exception:
    pass

_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
_TELEGRAM_API = f"https://api.telegram.org/bot{_BOT_TOKEN}" if _BOT_TOKEN else ""


def _format_telegram_summary(payload: Dict[str, Any]) -> str:
    tf = payload.get("timeframe", "?")
    th = payload.get("threshold")
    parts = [f"🔎 Scan results ({tf}), threshold ≥ {th}"]
    signals = payload.get("signals") or []
    if not signals:
        parts.append("— no matches.")
        return "\n".join(parts)

    for s in signals[:15]:
        sym = s.get("symbol")
        side = s.get("side") or "—"
        sc = s.get("score")
        note = s.get("note") or ""
        parts.append(f"• {sym}: {side}  score={sc}  {note}")
    if len(signals) > 15:
        parts.append(f"… +{len(signals)-15} more")
    return "\n".join(parts)


def _build_ops_urls(base_host: str, sig: Dict[str, Any], timeframe: str) -> Dict[str, str]:
    from urllib.parse import urlencode
    q = {
        "symbol": sig.get("symbol"),
        "side": sig.get("side"),
        "tf": timeframe,
        "score": sig.get("score"),
        "src": "scan",
    }
    qs = urlencode(q, doseq=False, safe=",:")
    approve = f"{base_host.rstrip('/')}/ops/approve?{qs}"
    reject = f"{base_host.rstrip('/')}/ops/reject?{qs}"
    return {"approve": approve, "reject": reject}


def _binance_chart_url(symbol: str, market: str, timeframe: str) -> str:
    sym = (symbol or "BTCUSDT").upper()
    if (market or "futures").lower().startswith("future"):
        return f"https://www.binance.com/en/futures/{sym}?interval={timeframe}"
    return f"https://www.binance.com/en/trade/{sym}?type=spot&interval={timeframe}"


async def _telegram_send_with_buttons(chat_id: str, text: str, buttons: List[List[Dict[str, str]]]) -> bool:
    if _send_message:
        try:
            _send_message(chat_id=chat_id, text=text, reply_markup={"inline_keyboard": buttons})  # type: ignore
            return True
        except Exception:
            pass
    if not _TELEGRAM_API:
        return False
    try:
        import httpx
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "reply_markup": {"inline_keyboard": buttons},
            "disable_web_page_preview": True,
        }
        async with httpx.AsyncClient(timeout=10.0) as cli:
            r = await cli.post(f"{_TELEGRAM_API}/sendMessage", json=payload)
            return bool(r.status_code == 200 and r.json().get("ok"))
    except Exception:
        return False


async def _telegram_send_text(chat_id: str, text: str) -> bool:
    if _send_text:
        try:
            _send_text(chat_id=chat_id, text=text)  # type: ignore
            return True
        except Exception:
            pass
    if _send_message:
        try:
            _send_message(chat_id=chat_id, text=text)  # type: ignore
            return True
        except Exception:
            pass
    if not _TELEGRAM_API:
        return False
    try:
        import httpx
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }
        async with httpx.AsyncClient(timeout=10.0) as cli:
            r = await cli.post(f"{_TELEGRAM_API}/sendMessage", json=payload)
            return bool(r.status_code == 200 and r.json().get("ok"))
    except Exception:
        return False


@router.get("/now", summary="Alias to /scan/top-volume (with threshold & optional rich Telegram notify)")
async def scan_now(
    request: Request,
    market: str = Query("futures"),
    quote: str = Query("USDT"),
    limit: int = Query(10, ge=1, le=100),
    timeframe: str = Query("15m"),
    kline_limit: int = Query(200, ge=60, le=1000),
    symbols: Optional[str] = Query(None, description="CSV e.g. BTCUSDT,ETHUSDT"),
    threshold: float = Query(6.0, description="Return only signals with score ≥ threshold"),
    notify: Optional[str] = Query(None, description='e.g. "telegram"'),
    chat_id: Optional[str] = Query(None, description="Telegram chat id"),
    rich: bool = Query(False, description="Send rich Telegram message with inline buttons if notify=telegram"),
) -> Dict[str, Any]:
    if not scan_top_volume:
        return {
            "ok": False,
            "error": "scan_top_volume not available (import failed)",
            "returned": 0,
            "count_total": 0,
        }

    symbol_single: Optional[str] = None
    if symbols:
        parts = [s.strip().upper() for s in symbols.split(",") if s.strip()]
        if len(parts) == 1:
            symbol_single = parts[0]

    base: Dict[str, Any] = await scan_top_volume(
        market=market,
        quote=quote,
        limit=limit,
        timeframe=timeframe,
        kline_limit=kline_limit,
        symbol=symbol_single,
    )  # type: ignore

    ok = bool(base.get("ok", False))
    items = list(base.get("signals") or [])
    if not ok:
        return {
            "ok": False,
            "error": base.get("error") or "scan_top_volume failed",
            "count_total": base.get("count_total", 0),
            "returned": 0,
            "signals": [],
        }

    filt = [s for s in items if isinstance(s, dict) and float(s.get("score", 0)) >= float(threshold)]

    out: Dict[str, Any] = {
        "ok": True,
        "market": market,
        "quote": quote,
        "timeframe": timeframe,
        "threshold": threshold,
        "count_total": len(items),
        "returned": len(filt),
        "signals": filt,
        "mode": base.get("mode", "compact"),
    }

    if notify and notify.lower() == "telegram":
        note = None
        sent = False

        if not chat_id:
            note = "notify=telegram requested but chat_id is missing"
        else:
            base_host = os.getenv("PUBLIC_HOST", "").strip() or str(request.base_url).rstrip("/")

            if rich:
                top = filt[:8] if len(filt) > 8 else filt
                if not top:
                    msg = _format_telegram_summary({"timeframe": timeframe, "threshold": threshold, "signals": []})
                    sent = await _telegram_send_text(chat_id=chat_id, text=msg)
                else:
                    buttons: List[List[Dict[str, str]]] = []
                    for sig in top:
                        urls = _build_ops_urls(base_host, sig, timeframe)
                        sym = sig.get("symbol")
                        side = sig.get("side")
                        chart = _binance_chart_url(sym, market, timeframe)

                        buttons.append([
                            {"text": f"✅ Approve {sym} {side}", "url": urls["approve"]},
                            {"text": f"⛔ Reject", "url": urls["reject"]},
                        ])
                        buttons.append([
                            {"text": f"📈 Chart {sym}", "url": chart}
                        ])

                    header = f"🔎 *Scan {timeframe}* (≥ {threshold}) — {len(top)}/{len(filt)} signals"
                    sent = await _telegram_send_with_buttons(chat_id=chat_id, text=header, buttons=buttons)
                    if not sent:
                        msg = _format_telegram_summary({"timeframe": timeframe, "threshold": threshold, "signals": top})
                        sent = await _telegram_send_text(chat_id=chat_id, text=msg)
            else:
                msg = _format_telegram_summary({"timeframe": timeframe, "threshold": threshold, "signals": filt})
                sent = await _telegram_send_text(chat_id=chat_id, text=msg)

        out["notified"] = bool(sent)
        if note:
            out["notify_note"] = note

    return out


__all__ = ["router"]




