# routes/system_autopilot.py
from __future__ import annotations
import os, time, asyncio, logging, json
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Body
from utils.binance_client import futures_exchange_info_safe, get_futures_client
from utils.auto_executor import execute_trade_live as exec_live

router = APIRouter(tags=["autopilot"])
log = logging.getLogger("algogpt.autopilot")

# ───────────────────────── Config (ENV) ─────────────────────────
AP_ENABLE                 = os.getenv("AUTOPILOT_ENABLE", "1").lower() in ("1","true","yes","on")
AP_INTERVAL_SEC           = float(os.getenv("AUTOPILOT_INTERVAL_SEC", "45"))
AP_MAX_PARALLEL           = int(os.getenv("AUTOPILOT_MAX_PARALLEL", "4"))
AP_SYMBOLS                = (os.getenv("AUTOPILOT_SYMBOLS", "ALL") or "ALL").strip()
AP_MAX_SYMBOLS            = int(os.getenv("AUTOPILOT_MAX_SYMBOLS", "250"))

AP_MIN_SCORE              = float(os.getenv("AUTOPILOT_MIN_SCORE", "7.0"))
AP_FALLBACK_SCORE         = float(os.getenv("AUTOPILOT_FALLBACK_SCORE", "6.0"))

AP_SIDE                   = (os.getenv("AUTOPILOT_SIDE", "BOTH") or "BOTH").upper()   # BUY/SELL/BOTH
AP_ALLOW_LONG             = os.getenv("AUTOPILOT_ALLOW_LONG",  "1").lower() in ("1","true","yes","on")
AP_ALLOW_SHORT            = os.getenv("AUTOPILOT_ALLOW_SHORT", "1").lower() in ("1","true","yes","on")

AP_CANDIDATES_PER_TICK    = int(os.getenv("AUTOPILOT_CANDIDATES_PER_TICK", "3"))
AP_DEDUP_MIN              = int(os.getenv("AUTOPILOT_DEDUP_MIN", "20"))  # דקות

AP_REQ_LEV                = int(float(os.getenv("AUTOPILOT_REQ_LEVERAGE", "0")))  # 0 => דינמי
AP_BUDGET_USDT_RAW        = os.getenv("AUTOPILOT_BUDGET_USDT", "").strip()       # "" => דינמי
AP_BUDGET_USDT            = float(AP_BUDGET_USDT_RAW) if AP_BUDGET_USDT_RAW else None

AP_TG_CHAT_ID             = int(os.getenv("TELEGRAM_CHAT_ID", "0") or "0")

# ───────────────────────── Runtime State ─────────────────────────
_task: Optional[asyncio.Task] = None
_stop_flag: bool = False
_last_tick_ms: int = 0
_last_info: Dict[str, Any] = {}
_dedup: Dict[str, float] = {}  # key = "SYM:BUY/SELL" -> ts
_lock = asyncio.Lock()

# ───────────────────────── Scanner bridge ───────────────────────
# ננסה להתחבר לסורק שלך אם קיים; אחרת נשתמש בגייט-לייט מובנה
def _maybe_find_external_scanners():
    candidates = []
    # נסיונות טעינה לפי קבצים שמופיעים בריפו שלך
    for path_mod, syms in [
        ("utils.scoring",            ("score_symbol","scan_universe","rank_symbols")),
        ("utils.quality_score",      ("score_symbol","score_symbols")),
        ("routes.scan",              ("scan_universe","scan_symbols","rank_symbols")),
        ("utils.multi_tf_scanner",   ("scan_universe","scan_symbols")),
    ]:
        try:
            mod = __import__(path_mod, fromlist=list(syms))
            candidates.append(mod)
        except Exception:
            continue
    return candidates

_EXT_SCANNERS = _maybe_find_external_scanners()

async def _external_score_symbol(symbol: str) -> Optional[List[Tuple[str, float, Dict[str, Any]]]]:
    """
    מנסה להשתמש בסורק חיצוני, מחזיר רשימת [(side, score, meta), ...]
    צד יכול להיות BUY/SELL. אם אין — מחליטים לפי שדות נפוצים.
    """
    for mod in _EXT_SCANNERS:
        # ניסיונות ממשק נפוצים:
        for fn_name in ("score_symbol",):
            fn = getattr(mod, fn_name, None)
            if callable(fn):
                try:
                    r = fn(symbol)  # סורקים רבים מחזירים dict סקור
                    # ננרמל:
                    if isinstance(r, dict):
                        # צורות מקובלות:
                        # {"score": 7.6, "side": "BUY"}
                        # {"long": 7.8, "short": 5.1}
                        out: List[Tuple[str, float, Dict[str, Any]]] = []
                        if "side" in r and "score" in r:
                            out.append((str(r["side"]).upper(), float(r["score"]), r))
                        else:
                            if "long" in r:
                                out.append(("BUY", float(r["long"]), r))
                            if "short" in r:
                                out.append(("SELL", float(r["short"]), r))
                        if out:
                            return out
                except Exception:
                    continue
        # אם יש פונקציות סריקה של יקום — אפשר להשתמש בהן בשאיבה מרוכזת (נשתמש בהמשך ל-universe)
    return None

def _ema(vals: List[float], period: int) -> List[float]:
    k = 2/(period+1); out=[]; s=None
    for v in vals:
        s = v if s is None else (v*k + s*(1-k))
        out.append(s)
    return out

def _gate_lite(symbol: str, side: str) -> Dict[str, Any]:
    """
    גיבוי כשאין סורק חיצוני: EMA21/EMA50 + מומנטום 3 נרות + ATR%(1m/14)
    """
    try:
        cli = get_futures_client()
        kl = cli.futures_klines(symbol=symbol, interval="1m", limit=60) or []
        closes = [float(r[4]) for r in kl]
        vols   = [float(r[5]) for r in kl]
        if len(closes) < 30:
            return {"enter_ok": False, "score": 0.0, "reasons": ["insufficient_data"], "met": {}}

        ema21 = _ema(closes, 21)[-1]
        ema50 = _ema(closes, 50)[-1]
        last  = closes[-1]

        # ATR לייט
        trs=[]; prev=None
        for r in kl:
            h=float(r[2]); l=float(r[3]); c=float(r[4])
            tr = (h-l) if prev is None else max(h-l, abs(h-prev), abs(l-prev))
            trs.append(tr); prev=c
        alpha = 1/14; atr=None
        for v in trs: atr = v if atr is None else (alpha*v+(1-alpha)*atr)
        atr = float(atr or 0.0)
        atr_pct = (atr/last)*100.0 if last>0 else 999.0

        mom = ((closes[-1]/closes[-4]) - 1.0)*100.0 if len(closes)>=4 and closes[-4]>0 else 0.0

        trend_ok = (ema21 > ema50 and last > ema21) if side=="BUY" else (ema21 < ema50 and last < ema21)
        mom_ok   = (mom > 0.05) if side=="BUY" else (mom < -0.05)
        atr_ok   = (atr_pct <= float(os.getenv("MAX_ATR_PCT","2.5")))

        score = (4.0 if trend_ok else 0.0) + (3.0 if mom_ok else 0.0) + (2.0 if atr_ok else 0.0) + 1.0
        enter_ok = (score >= AP_MIN_SCORE) or (score >= AP_FALLBACK_SCORE and atr_ok)

        return {
            "enter_ok": enter_ok,
            "score": round(float(score),2),
            "reasons": [r for r,ok in (("trend_mismatch",trend_ok),("weak_momentum",mom_ok),("atr_too_high",atr_ok)) if not ok],
            "met": {"ema21":ema21,"ema50":ema50,"atr_pct":atr_pct,"mom_pct":mom,"vol1m":vols[-1] if vols else None}
        }
    except Exception as e:
        log.warning("gate_lite failed %s: %s", symbol, e)
        return {"enter_ok": False, "score": 0.0, "reasons": ["gate_error"], "met": {}}

def _discover_universe() -> List[str]:
    if AP_SYMBOLS and AP_SYMBOLS.upper() != "ALL":
        return [s.strip().upper() for s in AP_SYMBOLS.split(",") if s.strip()]
    try:
        info = futures_exchange_info_safe(force_refresh=False) or {}
        syms = []
        for s in info.get("symbols", []):
            if (s.get("contractType") == "PERPETUAL" and
                s.get("quoteAsset") == "USDT" and
                s.get("status") == "TRADING"):
                syms.append(s.get("symbol"))
        syms = [x for x in syms if x]
        if AP_MAX_SYMBOLS and len(syms) > AP_MAX_SYMBOLS:
            syms = syms[:AP_MAX_SYMBOLS]
        return syms
    except Exception as e:
        log.warning("universe discovery failed: %s", e)
        return ["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT"]

def _dedup_allow(symbol: str, side: str) -> bool:
    key = f"{symbol}:{side}"
    now = time.time()
    ts = _dedup.get(key, 0.0)
    # חלון שמרני (בדקות) * 60 / 3 כדי לא להציף
    if now - ts < max(60, AP_DEDUP_MIN * 60 / 3):
        return False
    _dedup[key] = now
    # ניקוי מפה מדי פעם
    if len(_dedup) > 2000:
        for k, v in list(_dedup.items())[:400]:
            if now - v > AP_DEDUP_MIN * 60:
                _dedup.pop(k, None)
    return True

async def _score_one(symbol: str) -> List[Tuple[str, float, Dict[str, Any]]]:
    out: List[Tuple[str,float,Dict[str,Any]]] = []

    # סורק חיצוני (אם קיים אצלך)
    ext = await _external_score_symbol(symbol)
    if ext:
        for side, score, meta in ext:
            s = side.upper()
            if s == "BUY" and not AP_ALLOW_LONG:  continue
            if s == "SELL" and not AP_ALLOW_SHORT: continue
            out.append((s, float(score), meta))

    # אם אין חיצוני — נשתמש בגייט לייט
    if not out:
        for s in ("BUY","SELL"):
            if (s == "BUY" and not AP_ALLOW_LONG) or (s == "SELL" and not AP_ALLOW_SHORT):
                continue
            g = _gate_lite(symbol, s)
            if g.get("enter_ok"):
                out.append((s, float(g.get("score",0.0)), g))

    return out

async def _pick_candidates(universe: List[str]) -> List[Tuple[str,str,float,Dict[str,Any]]]:
    sides_whitelist = []
    if AP_SIDE in ("BUY","BOTH"):  sides_whitelist.append("BUY")
    if AP_SIDE in ("SELL","BOTH"): sides_whitelist.append("SELL")

    sem = asyncio.Semaphore(min(24, max(4, AP_MAX_PARALLEL*3)))
    results: List[Tuple[str,str,float,Dict[str,Any]]] = []

    async def worker(sym: str):
        async with sem:
            pairs = await _score_one(sym)
            for side, score, meta in pairs:
                if side not in sides_whitelist:
                    continue
                if score < AP_FALLBACK_SCORE:
                    continue
                if not _dedup_allow(sym, side):
                    continue
                results.append((sym, side, score, meta))

    await asyncio.gather(*(worker(s) for s in universe))
    # דירוג (score ואז מומנטום אם יש)
    def mom(meta: Dict[str,Any]) -> float:
        m = 0.0
        try:
            if isinstance(meta, dict):
                d = meta.get("met") or meta
                m = float(d.get("mom_pct") or d.get("mom") or 0.0)
        except Exception:
            pass
        return m

    results.sort(key=lambda t: (t[2], mom(t[3])), reverse=True)
    return results[:AP_CANDIDATES_PER_TICK]

async def _open_candidate(sym: str, side: str, score: float, meta: Dict[str,Any]) -> Dict[str,Any]:
    try:
        plan = await exec_live(
            sym, side,
            budget=AP_BUDGET_USDT,
            leverage=AP_REQ_LEV,
            dry_run=False,                    # מבצע בפועל, אך עם confirm_first=True
            confirm_first=True,
            telegram_chat_id=AP_TG_CHAT_ID,
        )
        return {"ok": True, "symbol": sym, "side": side, "score": score, "exec": plan}
    except Exception as e:
        return {"ok": False, "symbol": sym, "side": side, "score": score, "error": str(e)}

# ───────────────────────── Loop & API ──────────────────────────
async def _tick():
    global _last_tick_ms, _last_info
    uni = _discover_universe()
    cands = await _pick_candidates(uni)

    opened, errors = [], []
    if cands:
        sem = asyncio.Semaphore(AP_MAX_PARALLEL)
        async def do_one(sym, side, score, meta):
            async with sem:
                r = await _open_candidate(sym, side, score, meta)
                (opened if r.get("ok") else errors).append(r)
        await asyncio.gather(*(do_one(s,side,sc,m) for (s,side,sc,m) in cands))

    _last_tick_ms = int(time.time()*1000)
    _last_info = {
        "universe": len(uni),
        "candidates": [{"symbol":s,"side":side,"score":sc} for (s,side,sc,_) in cands],
        "opened": opened,
        "errors": errors,
    }

async def _run_forever():
    log.info({"event":"autopilot.start","enabled":AP_ENABLE,"interval_sec":AP_INTERVAL_SEC})
    while not _stop_flag:
        t0 = time.time()
        try:
            await _tick()
        except Exception as e:
            log.warning({"event":"autopilot.tick_error","err":str(e)})
        dt = time.time() - t0
        await asyncio.sleep(max(5.0, AP_INTERVAL_SEC - dt))
    log.info({"event":"autopilot.stop"})

def start():
    global _task, _stop_flag
    if _task and not _task.done():
        return
    _stop_flag = False
    loop = asyncio.get_event_loop()
    _task = loop.create_task(_run_forever())

def stop():
    global _stop_flag
    _stop_flag = True

def autostart():
    if not AP_ENABLE:
        log.info({"event":"autopilot.disabled"})
        return
    start()

@router.get("/autopilot/status")
async def autopilot_status():
    return {
        "ok": True,
        "running": bool(_task and not _task.done()),
        "interval_sec": AP_INTERVAL_SEC,
        "last_tick_ms": _last_tick_ms,
        "last": _last_info,
        "config": {
            "min_score": AP_MIN_SCORE,
            "fallback_score": AP_FALLBACK_SCORE,
            "side": AP_SIDE,
            "max_parallel": AP_MAX_PARALLEL,
            "tg_chat": AP_TG_CHAT_ID,
            "req_lev": AP_REQ_LEV,
            "budget_usdt": AP_BUDGET_USDT,
        }
    }

@router.post("/autopilot/start")
async def autopilot_start():
    async with _lock:
        autostart()
    return {"ok": True, "started": True}

@router.post("/autopilot/stop")
async def autopilot_stop():
    async with _lock:
        stop()
    return {"ok": True, "stopped": True}

