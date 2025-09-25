# app/signals_engine.py
from __future__ import annotations
import os, sys, asyncio, logging, shlex
from typing import Optional
from asyncio.subprocess import PIPE

from utils.signal_parser import parse_text_signal
from utils.mode_store import ExecMode
from utils.config import cfg_for_symbol  # אם השתמשת בגרסה הפשוטה שלי, החלף לשלה
from utils.trade_executor import execute_trade_live
from telegram.commands import poll_bot_commands, send_message

log = logging.getLogger("algogpt.signals_engine")
TELEGRAM_CHAT_ID = int(os.getenv("TELEGRAM_CHAT_ID", "0") or "0")
WATCH_SOURCE = os.getenv("WATCH_SOURCE", "stdin").lower()  # "stdin" | "process"
WATCH_CMD = os.getenv("WATCH_CMD", "/app/bw notify --symbols BTC,ETH --compact --watch")

def _setup_logging() -> None:
    LOG_PATH = os.getenv("ALGOGPT_LOG_PATH", "/app/logs/algogpt.log")
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    lvl = (os.getenv("LOG_LEVEL", "INFO") or "INFO").upper()
    logging.basicConfig(
        level=lvl,
        format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(LOG_PATH, encoding="utf-8")]
    )

async def _run_process_and_stream(cmd: str):
    args = shlex.split(cmd)
    proc = await asyncio.create_subprocess_exec(*args, stdout=PIPE, stderr=PIPE)
    log.info("watcher started: %s", cmd)
    try:
        while True:
            line = await proc.stdout.readline()
            if not line:
                await asyncio.sleep(0.2)
                continue
            yield line.decode("utf-8", "replace").strip()
    finally:
        try: proc.terminate()
        except Exception: pass

async def _read_stdin_lines():
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    loop = asyncio.get_event_loop()
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)
    while True:
        line = await reader.readline()
        if not line:
            await asyncio.sleep(0.2)
            continue
        yield line.decode("utf-8", "replace").strip()

async def _notify(signal: dict, result: dict, stage: str = "result") -> None:
    if not TELEGRAM_CHAT_ID: return
    try:
        dry = ExecMode.get() == "dry"
        side = signal.get("side"); sym = signal.get("symbol")
        qty  = signal.get("quantity"); lev = signal.get("leverage")
        ent  = signal.get("entry"); tp = signal.get("tp"); sl = signal.get("sl")
        ok   = bool(result.get("ok"))
        base = result.get("base_price") or result.get("entry_result",{}).get("price")
        entry_kind = (result.get("entry_result") or {}).get("entry_kind") if not result.get("dry_run") else "DRY"
        reason = result.get("reason") or ""
        qstr = f" qty={qty}" if qty else ""
        lstr = f" lev={lev}" if lev else ""
        tstr = f" tp={tp}" if tp else ""
        sstr = f" sl={sl}" if sl else ""
        if stage == "armed":
            tp_n = len(result.get("tp_orders") or [])
            sl_n = len(result.get("sl_orders") or [])
            await send_message(TELEGRAM_CHAT_ID, f"🛡️ Armed TP/SL: {sym} → TP={tp_n}, SL={sl_n}")
            return
        if ok:
            txt = (f"✅ <b>{'DRY' if dry else 'LIVE'}</b> {side} <b>{sym}</b>@{ent} "
                   f"{qstr}{lstr}{tstr}{sstr}\n"
                   f"mode={ExecMode.get().upper()} entry={entry_kind} base≈{base}")
        else:
            txt = (f"❌ <b>FAILED</b> {side} <b>{sym}</b>@{ent} "
                   f"{qstr}{lstr}{tstr}{sstr}\n"
                   f"reason={reason}")
        await send_message(TELEGRAM_CHAT_ID, txt, "HTML")
    except Exception as e:
        log.warning("notify failed: %s", e)

async def _handle_line(line: str) -> None:
    sig = parse_text_signal(line)
    if not sig:
        return
    dry_run = (ExecMode.get() == "dry")
    sym_cfg = cfg_for_symbol(sig["symbol"]) if 'cfg_for_symbol' in globals() else {}
    lev = int(sig.get("leverage") or sym_cfg.get("default_leverage") or os.getenv("MIN_LEVERAGE", 5))
    params = dict(
        symbol=sig["symbol"], side=sig["side"], entry=sig.get("entry"),
        quantity=sig.get("quantity"), leverage=lev, tp=sig.get("tp"), sl=sig.get("sl"),
        dry_run=dry_run, confirm_first=True, telegram_chat_id=TELEGRAM_CHAT_ID or None,
    )
    try:
        res = await execute_trade_live(**params)
    except Exception as e:
        res = {"ok": False, "reason": f"exception: {e}"}
    await _notify(sig, res, "result")
    if res.get("ok"):
        await _notify(sig, res, "armed")

async def main() -> None:
    _setup_logging()
    log.info("Signals engine starting… mode=%s source=%s", ExecMode.get().upper(), WATCH_SOURCE)
    asyncio.create_task(poll_bot_commands())  # polling לגיבוי
    if WATCH_SOURCE == "process":
        async for line in _run_process_and_stream(WATCH_CMD):
            if line: await _handle_line(line)
    else:
        async for line in _read_stdin_lines():
            if line: await _handle_line(line)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass


