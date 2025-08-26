# workers/watchdog.py
from __future__ import annotations
import os, time, json, asyncio, logging
from typing import Dict, Any, List

import httpx

from utils.hmac_utils import build_signed_outbound, generate_idempotency_key

LOGGER = logging.getLogger("watchdog")
logging.basicConfig(level=os.getenv("LOG_LEVEL","INFO").upper())

FUTURES_BASE = os.getenv("BINANCE_FUTURES_HTTP_BASE","https://fapi.binance.com")

ACTIVE_URL   = os.getenv("ALERTS_ACTIVE_URL","http://127.0.0.1:8000/alerts/trades/active")
UPDATE_URL   = os.getenv("ALERTS_UPDATE_URL","http://127.0.0.1:8000/alerts/trades/update")
ANALYSIS_URL = os.getenv("ALERTS_ANALYSIS_URL","http://127.0.0.1:8000/alerts/analysis")

WEBHOOK_HMAC_SECRET = os.getenv("WEBHOOK_HMAC_SECRET","").strip()
INTERVAL_SEC  = int(float(os.getenv("WATCHDOG_INTERVAL_SEC","20")))
NEAR_PCT      = float(os.getenv("WATCHDOG_NEAR_PCT","0.25"))  # % מרחק ל”כמעט”
SL_BE_ON_TP1  = os.getenv("SL_BE_ON_TP1","1").lower() in ("1","true","yes")

TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", os.getenv("ADMIN_CHAT_ID","")).strip()

async def _get_active() -> List[Dict[str, Any]]:
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(ACTIVE_URL)
        r.raise_for_status()
        return r.json().get("items",[])

async def _get_prices(symbols: List[str]) -> Dict[str, float]:
    if not symbols:
        return {}
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(f"{FUTURES_BASE}/fapi/v1/ticker/price")
        r.raise_for_status()
        arr = r.json()
    out = {}
    want = set(s.upper() for s in symbols)
    for it in arr:
        s = it.get("symbol")
        if s in want:
            try:
                out[s] = float(it.get("price"))
            except Exception:
                pass
    return out

async def _update_trade(tid: str, updates: Dict[str, Any]):
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(UPDATE_URL, json={"trade_id": tid, "updates": updates})
        r.raise_for_status()
        return r.json()

async def _notify(text: str, chat_id: str|int|None, reply_to: int|None = None, silent: bool = True):
    if not WEBHOOK_HMAC_SECRET or not chat_id:
        return
    payload = {"chat_id": chat_id, "text": text, "reply_to_message_id": reply_to, "silent": silent}
    body, headers = build_signed_outbound(
        WEBHOOK_HMAC_SECRET, payload,
        idempotency_key=generate_idempotency_key(),
        extra_headers={"Content-Type":"application/json"},
    )
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(ANALYSIS_URL, content=body, headers=headers)
        r.raise_for_status()

def _pct(a: float, b: float) -> float:
    try: return abs(a-b)/b*100.0 if b else 0.0
    except Exception: return 0.0

async def step():
    items = await _get_active()
    if not items:
        return
    symbols = [it.get("symbol","") for it in items if it.get("symbol")]
    prices = await _get_prices(symbols)

    for it in items:
        tid = str(it.get("trade_id"))
        sym = it.get("symbol","")
        ttype = it.get("trade_type","FUTURES").upper()
        chat_id = it.get("chat_id") or TELEGRAM_CHAT_ID

        price = prices.get(sym)
        if not price:
            continue

        # שחזור hits/near אם הם מחרוזות
        def parse_json(v, default):
            if isinstance(v, dict): return v
            if isinstance(v, str):
                try: return json.loads(v)
                except Exception: return default
            return default
        hits = parse_json(it.get("hits"), {"tp1":False,"tp2":False,"tp3":False,"sl":False})
        near = parse_json(it.get("near"), {"tp1":False,"tp2":False,"tp3":False,"sl":False})

        # נתמקד ב-FUTURES/SPOT (GRID מטופל אחרת)
        if ttype in ("FUTURES","SPOT"):
            entry = _f(it.get("entry")); sl = _f(it.get("sl"))
            tp1 = _f(it.get("tp1")); tp2 = _f(it.get("tp2")); tp3 = _f(it.get("tp3"))

            # near alerts
            if tp1: 
                if not near.get("tp1") and _pct(price, tp1) <= NEAR_PCT:
                    near["tp1"] = True
                    await _notify(f"⏳ {sym} כמעט TP1 ({price:.6f} ~ {tp1:.6f})", chat_id, silent=True)
            if tp2:
                if not near.get("tp2") and _pct(price, tp2) <= NEAR_PCT:
                    near["tp2"] = True
                    await _notify(f"⏳ {sym} כמעט TP2 ({price:.6f} ~ {tp2:.6f})", chat_id, silent=True)
            if tp3:
                if not near.get("tp3") and _pct(price, tp3) <= NEAR_PCT:
                    near["tp3"] = True
                    await _notify(f"⏳ {sym} כמעט TP3 ({price:.6f} ~ {tp3:.6f})", chat_id, silent=True)
            if sl:
                if not near.get("sl") and _pct(price, sl) <= NEAR_PCT:
                    near["sl"] = True
                    await _notify(f"⚠️ {sym} קרוב ל-SL ({price:.6f} ~ {sl:.6f})", chat_id, silent=True)

            # TP1 hit → SL→BE
            if tp1 and not hits.get("tp1"):
                crossed = (price >= tp1) if it.get("side","LONG") == "LONG" else (price <= tp1)
                if crossed:
                    hits["tp1"] = True
                    updates = {"hits": json.dumps(hits), "near": json.dumps(near)}
                    if SL_BE_ON_TP1 and entry:
                        updates["sl"] = float(entry)
                        await _notify(f"✅ {sym} TP1 — SL הוזז ל-BE ({entry:.6f})", chat_id, silent=False)
                    await _update_trade(tid, updates)
                    continue

            # TP2/TP3 hit
            if tp2 and not hits.get("tp2"):
                crossed = (price >= tp2) if it.get("side","LONG") == "LONG" else (price <= tp2)
                if crossed:
                    hits["tp2"] = True
                    await _notify(f"✅ {sym} TP2", chat_id, silent=False)
                    await _update_trade(tid, {"hits": json.dumps(hits), "near": json.dumps(near)})
                    continue
            if tp3 and not hits.get("tp3"):
                crossed = (price >= tp3) if it.get("side","LONG") == "LONG" else (price <= tp3)
                if crossed:
                    hits["tp3"] = True
                    await _notify(f"✅ {sym} TP3 — סגירה מלאה/חלקית לפי נוהל", chat_id, silent=False)
                    await _update_trade(tid, {"hits": json.dumps(hits), "near": json.dumps(near)})
                    continue

            # SL hit
            if sl and not hits.get("sl"):
                crossed = (price <= sl) if it.get("side","LONG") == "LONG" else (price >= sl)
                if crossed:
                    hits["sl"] = True
                    await _notify(f"🛑 {sym} SL הופעל", chat_id, silent=False)
                    await _update_trade(tid, {"hits": json.dumps(hits), "near": json.dumps(near)})
                    continue

        elif ttype == "GRID":
            # אפשר להרחיב: התראות על נגיעת קווי גריד, PnL מצטבר, וכו'.
            pass

def _f(x):
    try: 
        v = float(x)
        return v if v==v else None
    except Exception:
        return None

async def main():
    while True:
        try:
            await step()
            await asyncio.sleep(INTERVAL_SEC)
        except Exception as e:
            LOGGER.exception("watchdog error: %s", e)
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())
