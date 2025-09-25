# /app/app/signals_engine.py
from __future__ import annotations
import os, sys, shlex, asyncio, logging
from asyncio.subprocess import PIPE
from typing import Optional

import httpx

from utils.signal_parser import parse_text_signal
from utils.trade_executor import execute_trade_live

# אם יש לך סטרים קיים – נשתמש בו (לא חובה להריץ מכאן)
try:
    from utils.ws_user_stream import start as ws_start
except Exception:
    ws_start = None  # אין תלות קשיחה

log = logging.getLogger("signals_engine")

# ── Telegram ────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = int(os.getenv("TELEGRAM_CHAT_ID", "0") or "0")
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

async def tg_send(text: str, parse: Optional[str] = "HTML"):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    async with httpx.AsyncClient(timeout=10.0) as cli:
        await cli.post(f"{TELEGRAM_API}/sendMessage", json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            **({"parse_mode": "HTML"} if parse else {}),
        })

# ── Mode (ללא ENV חדשים) ───────────────────────────────────────────────
def _initial_mode() -> str:
    force = (os.getenv("ROUTES_ONLY") or "").strip().lower()  # משמש כ-FORCE_MODE
    if force in ("live", "dry"):
        return force
    dflt = (os.getenv("DEFAULT_MODE") or "").strip().lower()
    if dflt in ("live", "dry"):
        return dflt
    exec_trades = (os.getenv("EXECUTE_TRADES", "1")).strip().lower()
    return "live" if exec_trades in ("1", "true", "yes", "on") else "dry"

def _mode() -> str:
    return _initial_mode()

# ── Watch source ────────────────────────────────────────────────────────
WATCH_SOURCE = (os.getenv("WATCH_SOURCE") or "stdin").strip().lower()  # stdin|process
WATCH_CMD = (os.getenv("WATCH_CMD") or "").strip()

def _setup_logging():
    lvl = (os.getenv("LOG_LEVEL", "INFO") or "INFO").upper()
    logging.basicConfig(level=lvl, format="%(asctime)s %(levelname)s %(name)s :: %(message)s")

async def _run_process_and_yield(cmd: str):
    args = shlex.split(cmd)
    proc = await asyncio.create_subprocess_exec(*args, stdout=PIPE, stderr=PIPE)
    log.info("watch process started: %s", cmd)
    try:
        while True:
            line = await proc.stdout.readline()
            if not line:
                await asyncio.sleep(0.05)
                continue
            yield line.decode("utf-8", "replace").strip()
    finally:
        try: proc.terminate()
        except Exception: pass

async def _read_stdin():
    loop = asyncio.get_event_loop()
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)
    while True:
        line = await reader.readline()
        if not line:
            await asyncio.sleep(0.05)
            continue
        yield line.decode("utf-8", "replace").strip()

async def _handle_line(line: str):
    sig = parse_text_signal(line)
    if not sig:
        return
    mode = _mode()
    dry_run = (mode != "live")

    params = dict(
        symbol=sig["symbol"],
        side=sig["side"],
        entry=sig.get("entry"),
        quantity=sig.get("quantity"),
        leverage=int(sig.get("leverage") or os.getenv("MIN_LEVERAGE", "5")),
        tp=sig.get("tp"),
        sl=sig.get("sl"),
        dry_run=dry_run,
        confirm_first=True,
        telegram_chat_id=TELEGRAM_CHAT_ID or None,
    )

    try:
        res = await execute_trade_live(**params)
    except Exception as e:
        res = {"ok": False, "reason": f"exception: {e}"}

    sym, side, ent, tp, sl = sig.get("symbol"), sig.get("side"), sig.get("entry"), sig.get("tp"), sig.get("sl")
    if res.get("ok"):
        ek = (res.get("entry_result") or {}).get("entry_kind") or ("DRY" if dry_run else "LIVE")
        base = res.get("base_price") or (res.get("entry_result") or {}).get("price")
        await tg_send(f"✅ <b>{mode.upper()}</b> {side} <b>{sym}</b>@{ent} tp={tp} sl={sl}\nentry={ek} base≈{base}")
        tps = len(res.get("tp_orders") or [])
        sls = len(res.get("sl_orders") or [])
        await tg_send(f"🛡️ Armed: {sym} → TP={tps}, SL={sls}")
    else:
        await tg_send(f"❌ FAILED {side} <b>{sym}</b>@{ent}\nreason={res.get('reason')}")

async def _boot_user_stream_if_enabled():
    # אם יש לך USER_STREAM_ENABLE=1, והמימוש שלך קיים – נרים סטרים ברקע
    if os.getenv("USER_STREAM_ENABLE", "0").strip().lower() in ("1", "true", "yes", "on"):
        if ws_start:
            try:
                ws_start()
                log.info("user-stream started (utils.ws_user_stream)")
            except Exception as e:
                log.warning("user-stream start failed: %s", e)
        else:
            log.info("user-stream not available (utils.ws_user_stream not found)")

async def main():
    _setup_logging()
    log.info("signals engine start; mode=%s source=%s", _mode(), WATCH_SOURCE)
    await _boot_user_stream_if_enabled()

    if WATCH_SOURCE == "process" and WATCH_CMD:
        async for line in _run_process_and_yield(WATCH_CMD):
            if line:
                await _handle_line(line)
    else:
        async for line in _read_stdin():
            if line:
                await _handle_line(line)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass



