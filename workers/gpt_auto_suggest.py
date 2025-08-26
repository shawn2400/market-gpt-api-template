# workers/trade_watchdog.py
from __future__ import annotations
import os, time, asyncio, logging, json
from typing import Dict, Any, Optional, List

import httpx
import websockets

from utils.trade_store import list_active, update_trade

BINANCE_FUTURES_HTTP_BASE = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com")
WS_URL = os.getenv("BINANCE_FUTURES_WS", "wss://fstream.binance.com/stream?streams=!miniTicker@arr")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN","")
ADMIN_CHAT_ID      = os.getenv("ADMIN_CHAT_ID","")
POLL_INTERVAL_SEC  = int(float(os.getenv("WATCHDOG_INTERVAL_SECONDS","20")))
USE_WS             = os.getenv("WATCHDOG_USE_WS","1").lower() in ("1","true","yes")
BATCH_REFRESH_SEC  = int(float(os.getenv("WATCHDOG_BATCH_REFRESH_SEC","30")))
STALE_SEC          = int(float(os.getenv("WATCHDOG_STALE_SEC","15")))
PROGRESS_EVERY_SEC = int(float(os.getenv("WATCHDOG_PROGRESS_EVERY_SEC","0")))  # 0=כבוי

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("trade_watchdog")

_PRICES: Dict[str, float] = {}
_TS: Dict[str, float] = {}
_LAST_BATCH_TS: float = 0.0
_LAST_PROGRESS: Dict[str, float] = {}

def _set_price(sym: str, p: float):
    _PRICES[sym] = float(p)
    _TS[sym] = time.time()

def get_price_cached(sym: str) -> Optional[float]:
    p = _PRICES.get(sym)
    if p is None: return None
    if (time.time() - _TS.get(sym, 0)) > STALE_SEC:
        return None
    return p

async def _tg_send(text: str, kb: Optional[dict] = None):
    if not TELEGRAM_BOT_TOKEN or not ADMIN_CHAT_ID: return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": ADMIN_CHAT_ID, "text": text, "parse_mode": "HTML"}
    if kb: payload["reply_markup"] = kb
    try:
        async with httpx.AsyncClient(timeout=8) as c:
            await c.post(url, json=payload)
    except Exception as e:
        log.warning({"event":"tg_send_fail","err":str(e)})

async def _refresh_prices_batch():
    global _LAST_BATCH_TS
    try:
        async with httpx.AsyncClient(timeout=6) as c:
            r = await c.get(f"{BINANCE_FUTURES_HTTP_BASE}/fapi/v1/ticker/price")
            if r.status_code == 200:
                for it in r.json():
                    s = it.get("symbol"); pr = it.get("price")
                    if s and pr is not None:
                        try: _set_price(str(s).upper(), float(pr))
                        except Exception: pass
                _LAST_BATCH_TS = time.time()
    except Exception as e:
        log.warning({"event":"batch_price_fail","err":str(e)})

async def _ws_loop():
    while True:
        try:
            async with websockets.connect(WS_URL, ping_interval=20, ping_timeout=20) as ws:
                log.info({"event":"ws_connected","url":WS_URL})
                async for msg in ws:
                    try:
                        j = json.loads(msg)
                        data = j.get("data")
                        if isinstance(data, list):
                            for it in data:
                                s = str(it.get("s","")).upper()
                                c = it.get("c")
                                if s and c is not None:
                                    _set_price(s, float(c))
                        elif isinstance(data, dict):
                            s = str(data.get("s","")).upper()
                            c = data.get("c")
                            if s and c is not None:
                                _set_price(s, float(c))
                    except Exception:
                        continue
        except Exception as e:
            log.warning({"event":"ws_disconnected","err":str(e)})
        await asyncio.sleep(2)

def _cross_up(p: float, level: float) -> bool:
    return p is not None and level is not None and p >= level

def _cross_down(p: float, level: float) -> bool:
    return p is not None and level is not None and p <= level

def _progress_ok(tid: str) -> bool:
    if PROGRESS_EVERY_SEC <= 0: return False
    last = _LAST_PROGRESS.get(tid, 0)
    if time.time() - last >= PROGRESS_EVERY_SEC:
        _LAST_PROGRESS[tid] = time.time()
        return True
    return False

def _pct(a: float, b: float) -> float:
    try:
        return 100.0 * (a/b - 1.0)
    except Exception:
        return 0.0

async def loop():
    ws_task = asyncio.create_task(_ws_loop()) if USE_WS else None

    while True:
        try:
            act = list_active()
            symbols = [ (tr.get("symbol") or tr.get("proposal",{}).get("symbol")) for tr in act if (tr.get("symbol") or tr.get("proposal",{}).get("symbol")) ]
            need_batch = any(get_price_cached(s) is None for s in set(symbols))
            if need_batch or (time.time()-_LAST_BATCH_TS) > BATCH_REFRESH_SEC:
                await _refresh_prices_batch()

            for tr in act:
                prop = tr.get("proposal",{})
                sym  = tr.get("symbol") or prop.get("symbol")
                if not sym: continue
                side = str(prop.get("side","LONG")).upper()
                entry= float(prop.get("entry") or 0)
                sl   = float(prop.get("sl") or 0)
                tp1  = float(prop.get("tp1") or 0)
                tp2  = float(prop.get("tp2") or 0)
                tp3  = float(prop.get("tp3") or 0)
                status = str(tr.get("status","TRACKED")).upper()
                tid = tr.get("id")
                price = get_price_cached(sym)
                if price is None: continue

                # Entry open
                if status in {"TRACKED","PENDING"} and not tr.get("flags",{}).get("opened"):
                    if (side=="LONG" and _cross_up(price, entry)) or (side=="SHORT" and _cross_down(price, entry)):
                        update_trade(tid, {"status":"OPEN", "flags": {**(tr.get("flags") or {}), "opened": True}})
                        await _tg_send(f"🚀 <b>{sym}</b> נפתח ~<b>{price:.6f}</b> (TP1: {tp1}, SL: {sl})")
                        continue

                flags = tr.get("flags") or {}

                # TP1
                if status=="OPEN" and not flags.get("tp1"):
                    hit = (_cross_up(price, tp1) if side=="LONG" else _cross_down(price, tp1))
                    if hit:
                        flags["tp1"] = True
                        update_trade(tid, {"flags": flags})
                        kb = {"inline_keyboard":[[
                            {"text":"🔒 עדכן SL → BE","callback_data": f"slbe:{tid}"}
                        ]]}
                        await _tg_send(f"✅ <b>{sym}</b> הגיע ל־TP1 ({tp1:.6f}).", kb)
                        continue

                # TP2
                if status=="OPEN" and not flags.get("tp2"):
                    hit = (_cross_up(price, tp2) if side=="LONG" else _cross_down(price, tp2))
                    if hit:
                        flags["tp2"] = True
                        update_trade(tid, {"flags": flags})
                        await _tg_send(f"🟩 <b>{sym}</b> הגיע ל־TP2 ({tp2:.6f}).")
                        continue

                # TP3 → close
                if status=="OPEN" and not flags.get("tp3"):
                    hit = (_cross_up(price, tp3) if side=="LONG" else _cross_down(price, tp3))
                    if hit:
                        flags["tp3"] = True
                        update_trade(tid, {"flags": flags, "status":"CLOSED", "state_CLOSED_ts": int(time.time())})
                        await _tg_send(f"🏁 <b>{sym}</b> הגיע ל־TP3 ({tp3:.6f}). נסגר.")
                        continue

                # SL
                if status=="OPEN" and not flags.get("sl"):
                    hit = (_cross_down(price, sl) if side=="LONG" else _cross_up(price, sl))
                    if hit:
                        flags["sl"] = True
                        update_trade(tid, {"flags": flags, "status":"CLOSED", "state_CLOSED_ts": int(time.time())})
                        await _tg_send(f"⛔ <b>{sym}</b> פגע ב־SL ({sl:.6f}). נסגר.")
                        continue

                # Progress ping (קליל)
                if status=="OPEN" and _progress_ok(tid):
                    pct_to_tp1 = _pct(price, tp1) if side=="LONG" else _pct(tp1, price)
                    pct_to_sl  = _pct(sl, price) if side=="LONG" else _pct(price, sl)
                    txt = f"ℹ️ <b>{sym}</b> | מחיר {price:.6f} | →TP1≈ {pct_to_tp1:.2f}% | →SL≈ {pct_to_sl:.2f}%"
                    await _tg_send(txt)

        except Exception as e:
            log.error({"event":"watchdog_err","err":str(e)})

        await asyncio.sleep(POLL_INTERVAL_SEC)

if __name__ == "__main__":
    asyncio.run(loop())











