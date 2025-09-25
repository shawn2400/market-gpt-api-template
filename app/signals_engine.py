# app/signals_engine.py
from __future__ import annotations
import os, sys, re, asyncio, logging, json, inspect
from typing import Optional, Dict, Any, List
import httpx

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("algogpt.signals_engine")

TG_TOKEN = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
TG_CHAT  = int(os.getenv("TELEGRAM_CHAT_ID", "0") or "0")

def _mode() -> str:
    force = (os.getenv("ROUTES_ONLY") or "").strip().lower()
    if force in ("live", "dry"):
        return force
    exec_trades = (os.getenv("EXECUTE_TRADES", "0").strip().lower() in ("1","true","yes","on"))
    return "live" if exec_trades else "dry"

async def _tg_send(text: str) -> None:
    if not TG_TOKEN or not TG_CHAT:
        log.info({"event":"tg_skip","reason":"no_token_or_chat"})
        return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    payload = {"chat_id": TG_CHAT, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    to = httpx.Timeout(10.0, connect=10.0)
    try:
        async with httpx.AsyncClient(timeout=to) as cli:
            await cli.post(url, data=payload)
    except Exception as e:
        log.warning({"event":"tg_send_failed","err":str(e)})

# ---------- signal parser ----------
_SIG_RX = re.compile(
    r"(?P<symbol>[A-Z0-9]{3,15})\s+"
    r"(?P<side>LONG|SHORT|BUY|SELL)\s+"
    r"(?:entry=?(?P<entry>[\d\.]+))?.*?"
    r"(?:sl=?(?P<sl>[\d\.]+))?.*?"
    r"(?:tp=?(?P<tp>[\d\.,]+))?.*?"
    r"(?:lev=?(?P<lev>[\d\.]+))?.*?"
    r"(?:qty=?(?P<qty>[\d\.]+))?",
    re.IGNORECASE,
)

def _parse_line(line: str) -> Optional[Dict[str, Any]]:
    m = _SIG_RX.search(line or "")
    if not m:
        return None
    tp_raw = (m.group("tp") or "").replace(" ", "")
    tps: List[float] = [float(x) for x in tp_raw.split(",") if x] if tp_raw else []
    side = (m.group("side") or "").upper()
    if side == "BUY": side = "LONG"
    if side == "SELL": side = "SHORT"
    return {
        "symbol": (m.group("symbol") or "").upper(),
        "side":   side,
        "entry":  float(m.group("entry") or 0.0),
        "sl":     float(m.group("sl") or 0.0),
        "tps":    tps,
        "lev":    float(m.group("lev") or 0.0),
        "qty":    float(m.group("qty") or 0.0),
    }

# ---------- executor adapter ----------
async def _execute_via_trade_executor(sig: Dict[str, Any], *, dry: bool) -> Dict[str, Any]:
    """
    מתאים ל-execute_trade_live שלך (kwargs). מנסה גם app.trade_executor וגם utils.trade_executor.
    """
    exc = None
    execute_trade_live = None
    for modpath in ("app.trade_executor", "utils.trade_executor"):
        try:
            mod = __import__(modpath, fromlist=["execute_trade_live"])
            execute_trade_live = getattr(mod, "execute_trade_live")
            break
        except Exception as e:
            exc = e
            continue
    if not execute_trade_live:
        raise RuntimeError(f"trade_executor missing: {exc}")

    # בניית kwargs לפי החתימה בפועל שלך
    kwargs: Dict[str, Any] = {
        "symbol": sig["symbol"],
        "side": sig["side"],  # LONG/SHORT ייתמך אצלך ומנורמל ל-BUY/SELL
        "dry_run": bool(dry),
    }
    if sig.get("entry", 0) > 0: kwargs["entry"] = float(sig["entry"])
    if sig.get("sl", 0)    > 0: kwargs["sl"]    = float(sig["sl"])
    if sig.get("tps"):           kwargs["tp_targets"] = list(sig["tps"])
    if sig.get("lev", 0)  > 0:   kwargs["leverage"]   = int(float(sig["lev"]))
    if sig.get("qty", 0)  > 0:   kwargs["quantity"]   = float(sig["qty"])

    # אפשר להעביר chat id אם קיים, ובמצב dry לא לדרוש אישור
    if os.getenv("TELEGRAM_CHAT_ID"):
        try:
            kwargs["telegram_chat_id"] = int(os.getenv("TELEGRAM_CHAT_ID", "0") or "0")
        except Exception:
            pass
    if dry:
        kwargs["confirm_first"] = False  # ללא אישור ידני בסימולציה

    # הפונקציה אצלך async – נקרא ישירות
    return await execute_trade_live(**kwargs)  # type: ignore

async def _start_user_stream_if_enabled():
    if (os.getenv("USER_STREAM_ENABLE","0").strip().lower() in ("1","true","on","yes")):
        try:
            try:
                from utils.ws_user_stream import start_async as _ws_start
            except Exception:
                from utils.user_stream import start_user_stream_consumer as _ws_start
            await _ws_start()
            log.info({"event":"user_stream_started"})
        except Exception as e:
            log.warning({"event":"user_stream_failed_to_start","err":str(e)})

async def handle_signal(sig: Dict[str, Any]):
    mode = _mode()
    await _tg_send(
        "📥 <b>Signal</b> [{mode}] {sym} {side}\nentry={entry} sl={sl} tp={tps} lev={lev} qty={qty}".format(
            mode=mode,
            sym=sig["symbol"],
            side=sig["side"],
            entry=sig.get("entry") or "–",
            sl=sig.get("sl") or "–",
            tps=",".join(map(str, sig.get("tps") or [])) or "–",
            lev=sig.get("lev") or "–",
            qty=sig.get("qty") or "–",
        )
    )

    dry = (mode == "dry")
    try:
        res = await _execute_via_trade_executor(sig, dry=dry)
        # הודעה מקוצרת כדי לא לחרוג מאורך
        await _tg_send(f"✅ {('DRY ' if dry else '')}Executed {sig['symbol']} {sig['side']} | {json.dumps(res)[:400]}")
    except Exception as e:
        log.warning({"event":"execute_failed","err":str(e)})
        await _tg_send(f"⚠️ Execution failed via trade_executor\n{e}")

async def main():
    await _start_user_stream_if_enabled()

    src = (os.getenv("WATCH_SOURCE") or "stdin").strip().lower()
    cmd = os.getenv("WATCH_CMD", "")
    await _tg_send(f"🚀 Signals engine started. Mode: <b>{_mode().upper()}</b> (source={src})")

    if src == "stdin":
        for line in sys.stdin:
            line = (line or "").strip()
            if not line:
                continue
            s = _parse_line(line)
            if not s:
                continue
            await handle_signal(s)
        return

    if src == "process":
        if not cmd.strip():
            log.error({"event":"process_source_missing_cmd"})
            return
        proc = await asyncio.create_subprocess_shell(
            cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
        )
        assert proc.stdout is not None
        async for raw in proc.stdout:
            line = raw.decode("utf-8", "ignore").strip()
            if not line:
                continue
            s = _parse_line(line)
            if not s:
                continue
            await handle_signal(s)
        return

    log.error({"event":"unknown_watch_source","value":src})

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass






