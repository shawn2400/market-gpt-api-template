# app/signals_engine.py
from __future__ import annotations
import os, sys, re, asyncio, logging, json
from typing import Optional, Dict, Any

# local minimal TG sender (no extra deps)
import httpx

log = logging.getLogger("algogpt.signals_engine")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

TG_TOKEN = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
TG_CHAT  = int(os.getenv("TELEGRAM_CHAT_ID", "0") or "0")

def _mode() -> str:
    force = (os.getenv("ROUTES_ONLY") or "").strip().lower()
    if force in ("live", "dry"): return force
    exec_trades = (os.getenv("EXECUTE_TRADES", "0").strip().lower() in ("1","true","yes","on"))
    return "live" if exec_trades else "dry"

async def _tg_send(text: str) -> None:
    if not TG_TOKEN or not TG_CHAT:
        log.info({"event":"tg_skip", "reason":"no_token_or_chat"})
        return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    payload = {"chat_id": TG_CHAT, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    timeout = httpx.Timeout(10.0, connect=10.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as cli:
            await cli.post(url, data=payload)
    except Exception as e:
        log.warning({"event":"tg_send_failed", "err": str(e)})

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
    if not m: return None
    tp_raw = (m.group("tp") or "").replace(" ", "")
    tps = [float(x) for x in tp_raw.split(",") if x] if tp_raw else []
    return {
        "symbol": m.group("symbol").upper(),
        "side":   m.group("side").upper(),
        "entry":  float(m.group("entry") or 0.0),
        "sl":     float(m.group("sl") or 0.0),
        "tps":    tps,
        "lev":    float(m.group("lev") or 0.0),
        "qty":    float(m.group("qty") or 0.0),
    }

async def _start_user_stream_if_enabled():
    # Use existing flags only; no new envs
    if (os.getenv("USER_STREAM_ENABLE", "0").lower() in ("1","true","on","yes")):
        try:
            # prefers your existing implementation if available
            try:
                from utils.ws_user_stream import start_async as _ws_start
            except Exception:
                from utils.user_stream import start_user_stream_consumer as _ws_start
            await _ws_start()
            log.info({"event":"user_stream_started"})
        except Exception as e:
            log.warning({"event":"user_stream_failed_to_start", "err": str(e)})

async def main():
    await _start_user_stream_if_enabled()
    src = (os.getenv("WATCH_SOURCE") or "stdin").lower()
    cmd = os.getenv("WATCH_CMD", "")

    mode = _mode()
    await _tg_send(f"🚀 Signals engine started. Mode: <b>{mode.upper()}</b> (source={src})")

    # Source: stdin
    if src == "stdin":
        for line in sys.stdin:
            line = (line or "").strip()
            if not line: continue
            sig = _parse_line(line)
            if not sig:
                log.info({"event":"skip_line", "line": line})
                continue
            await handle_signal(sig)
        return

    # Source: process (spawn WATCH_CMD)
    if src == "process":
        if not cmd.strip():
            log.error({"event":"process_source_missing_cmd"})
            return
        log.info({"event":"spawning_process", "cmd": cmd})
        proc = await asyncio.create_subprocess_shell(
            cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
        )
        assert proc.stdout is not None
        async for raw in proc.stdout:
            line = raw.decode("utf-8", "ignore").strip()
            if not line: continue
            sig = _parse_line(line)
            if not sig:
                continue
            await handle_signal(sig)
        return

    log.error({"event":"unknown_watch_source", "value": src})

async def handle_signal(sig: Dict[str, Any]):
    mode = _mode()
    sym, side = sig["symbol"], sig["side"]
    entry, sl, qty = sig["entry"], sig["sl"], sig["qty"]
    tps = sig["tps"]

    # Telegram summary before/after (no new envs)
    await _tg_send(
        f"📥 <b>Signal</b> [{mode}] {sym} {side}\n"
        f"entry={entry or '–'} sl={sl or '–'} tp={','.join([str(x) for x in tps]) or '–'} "
        f"lev={sig.get('lev') or '–'} qty={qty or '–'}"
    )

    if mode == "dry":
        log.info({"event":"dry_run", "sig": sig})
        return

    # LIVE: wire to your existing executor if available
    try:
        # try to use your stack if it exists
        from app.trade_executor import execute_trade_live  # type: ignore
        res = await execute_trade_live(sig)  # your function should be async; if not, wrap in to_thread
        await _tg_send(f"✅ Executed {sym} {side} | result={json.dumps(res)[:300]}")
    except Exception as e:
        # fallback: just acknowledge
        log.warning({"event":"execute_fallback", "err": str(e)})
        await _tg_send(f"⚠️ Executed (mock) {sym} {side} — hook missing.\n{e}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass




