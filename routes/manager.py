from __future__ import annotations
import os, json, time, hashlib, asyncio, logging, math
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from math import copysign

import httpx
from fastapi import APIRouter, HTTPException, Header, Body
from pydantic import BaseModel

# ===== Utilities / Optional modules (all soft-deps with graceful fallbacks) =====
from utils.anti_replay import verify_request
from utils.metrics_tracker import observe_http_ctx_async  # מטריקות עוטפות HTTP

# 🔔 אירועים (Redis + Telegram) — fallback רך אם המודול חסר
try:
    from utils.telegram_notifier import send_trade_approval  # type: ignore
except Exception:
    async def send_trade_approval(*_args, **_kwargs):
        return {"ok": False, "skipped": True, "reason": "telegram_notifier_unavailable"}

try:
    from utils.pos_events import emit  # type: ignore
except Exception:
    async def emit(*_args, **_kwargs):  # type: ignore
        return {"ok": False, "skipped": True, "reason": "pos_events_unavailable"}

try:
    from routes.position_ops import manage_once as position_ops_manage_once   # type: ignore
except Exception:
    position_ops_manage_once = None

try:
    from utils.position_manager import manage_once as pm_manage_once          # type: ignore
except Exception:
    pm_manage_once = None

try:
    from routes.position_ops import rewrite_native_tpsl as position_ops_rewrite_native_tpsl  # type: ignore
except Exception:
    position_ops_rewrite_native_tpsl = None

try:
    from utils.position_manager import rewrite_native_tpsl as pm_rewrite_native_tpsl  # type: ignore
except Exception:
    pm_rewrite_native_tpsl = None

try:
    from utils.trade_client import TradeClient  # type: ignore
except Exception:
    TradeClient = None  # type: ignore

try:
    from utils.account_state import get_positions_snapshot  # type: ignore
except Exception:
    get_positions_snapshot = None

try:
    from utils.indicators import eval_regime  # type: ignore
except Exception:
    eval_regime = None

try:
    from utils.indicators import ema, rsi, atr, adx, macd  # לחישובי ATR/ADX מהירים אם צריך
except Exception:
    ema = rsi = atr = adx = macd = None  # type: ignore

try:
    from utils.open_trade_manager_state import TradePlan, TradeStateManager  # type: ignore
    _STATE_MACHINE_AVAILABLE = True
except Exception:
    TradePlan = None      # type: ignore
    TradeStateManager = None  # type: ignore
    _STATE_MACHINE_AVAILABLE = False

# ===== Prometheus (soft dependency) =====
try:
    from prometheus_client import Counter, Summary
except Exception:  # graceful no-op fallbacks
    class _Noop:
        def labels(self, *args, **kwargs): return self
        def inc(self, *args, **kwargs): return None
        def observe(self, *args, **kwargs): return None
    Counter = Summary = lambda *a, **k: _Noop()  # type: ignore

logger = logging.getLogger("algogpt.manager")
router = APIRouter(tags=["manager"])

BASE_DIR   = Path(os.getenv("BASE_DIR", "/app"))
INGEST_DIR = Path(os.getenv("INGEST_DIR", str(BASE_DIR / "static" / "cache")))

MANAGER_ENABLE       = os.getenv("MANAGER_ENABLE", "1").lower() in ("1","true","yes","on")
MANAGER_INTERVAL_SEC = int(os.getenv("MANAGER_INTERVAL_SEC", "30"))
CONFIRMSTORE_ENABLE  = os.getenv("CONFIRMSTORE_ENABLE", "1").lower() in ("1","true","yes","on")

PUBLIC_HOST = (os.getenv("PUBLIC_HOST", "") or os.getenv("WEBHOOK_HOST", "")).rstrip("/")
ALERTS_INGEST_URL = os.getenv("ALERTS_INGEST_URL", f"{PUBLIC_HOST}/alerts/ingest").strip()
API_TOKEN = os.getenv("API_TOKEN", os.getenv("PRIMARY_API_TOKEN", "")).strip()
API_BEARER_TOKEN = (os.getenv("API_BEARER_TOKEN") or os.getenv("API_TOKEN") or "").strip()
HTTP_TIMEOUT = float(os.getenv("MANAGER_HTTP_TIMEOUT", "10.0"))

DEFAULT_QTY       = float(os.getenv("DEFAULT_QTY", "0.001"))
DEFAULT_LEVERAGE  = int(os.getenv("DEFAULT_LEVERAGE", "5"))
DEFAULT_TF        = os.getenv("DEFAULT_INTERVAL", "15m")

MANAGER_WRITES_ORDERS = os.getenv("MANAGER_WRITES_ORDERS", "1").lower() in ("1","true","yes","on")
NATIVE_TPSL_ENABLE    = os.getenv("NATIVE_TPSL_ENABLE", "0").lower() in ("1","true","yes","on")
ORDER_TRIGGER         = os.getenv("ORDER_TRIGGER", "mark").lower()  # mark|last

# === Regime / Auto-Flip rules
AUTO_FLIP_ENABLE   = os.getenv("AUTO_FLIP_ENABLE", "1").lower() in ("1","true","yes","on")
AUTO_FLIP_NEUTRAL  = os.getenv("AUTO_FLIP_NEUTRAL", "1").lower() in ("1","true","yes","on")
LONG_REQ           = os.getenv("LONG_REQ",  os.getenv("BTC_LONG_REQ",  "ema21>=ema50"))
SHORT_REQ          = os.getenv("SHORT_REQ", os.getenv("BTC_SHORT_REQ", "ema21<=ema50"))
NEUTRAL_REQ        = os.getenv("NEUTRAL_REQ", "")

# === Smart manage defaults
PROFILE_BASE_BE_BPS   = float(os.getenv("PROFILE_BASE_BE_BPS", "5"))
SMART_MANAGE_PCTS     = [float(x) for x in (os.getenv("SMART_MANAGE_PCTS", "4,8,16").split(","))]
SMART_MANAGE_SPLITS   = [float(x) for x in (os.getenv("SMART_MANAGE_SPLITS", "0.3,0.3,0.4").split(","))]
TRAIL_ATR_MULT        = float(os.getenv("TRAIL_ATR_MULT", os.getenv("TRAIL_DEFAULT_ATR_MULT","1.6")))

ANTI_REPLAY_REQUIRE_SIGNATURE = os.getenv("ANTI_REPLAY_REQUIRE_SIGNATURE", "1").lower() in ("1","true","yes","on")

# ===== Binance / WS =====
BINANCE_WS_BASE = os.getenv("BINANCE_FUTURES_WS_BASE", os.getenv("BINANCE_FAPI", "wss://fstream.binance.com/ws")).rstrip("/")
USE_WS          = os.getenv("USE_WS", "1").lower() in ("1","true","yes","on")
WS_KEEPALIVE_SEC= int(os.getenv("WS_KEEPALIVE_SEC", "25"))

# === WS Auto-Flip control
AF_EVAL_COOLDOWN_SEC   = int(os.getenv("AUTOFLIP_EVAL_COOLDOWN_SEC", "20"))
AF_FLIP_COOLDOWN_SEC   = int(os.getenv("AUTOFLIP_FLIP_COOLDOWN_SEC", "120"))
AF_MOVE_TRIGGER_BPS    = float(os.getenv("AUTOFLIP_MOVE_BPS", "3"))
AF_MAX_SYMBOLS         = int(os.getenv("AUTOFLIP_MAX_SYMBOLS", "20"))
AF_PRICE_TTL_SEC       = int(os.getenv("PRICE_WS_FRESH_TTL", "60"))
AF_WATCHLIST           = [s.strip().upper() for s in (os.getenv("WATCHLIST", "") or "").split(",") if s.strip()]

# === RT Trailing / BE / Locks (existing)
TRAIL_RT_ENABLE         = os.getenv("TRAIL_RT_ENABLE", "1") in ("1","true","yes","on")
TRAIL_RT_INTERVAL_SEC   = int(os.getenv("TRAIL_RT_INTERVAL_SEC", "20"))
TRAIL_RT_ATR_MULT       = float(os.getenv("TRAIL_RT_ATR_MULT", os.getenv("TRAIL_ATR_MULT","1.6")))
TRAIL_RT_MIN_CALLBACK   = float(os.getenv("TRAIL_RT_MIN_CALLBACK", "0.1"))
TRAIL_RT_MAX_CALLBACK   = float(os.getenv("TRAIL_RT_MAX_CALLBACK", "5.0"))
TRAIL_RT_ADJUST_THRESHOLD = float(os.getenv("TRAIL_RT_ADJUST_THRESHOLD", "0.2"))  # אחוז מה-ATR לשינוי לפני הזזה
TRAIL_RT_MAX_SYMBOLS    = int(os.getenv("TRAIL_RT_MAX_SYMBOLS", "20"))

TP_BE_OFFSET_BPS        = float(os.getenv("TP_BE_OFFSET_BPS", "12"))
SMART_MANAGE_BE_OFFSET_BPS = float(os.getenv("SMART_MANAGE_BE_OFFSET_BPS", str(PROFILE_BASE_BE_BPS)))

BE_GUARD_ENABLE         = os.getenv("BE_GUARD_ENABLE", "1") in ("1","true","yes","on")
BE_BASE_BPS             = float(os.getenv("BE_BASE_BPS", "5"))
BE_ADX_FACTOR           = float(os.getenv("BE_ADX_FACTOR", "0.2"))
BE_MIN_BPS              = float(os.getenv("BE_MIN_BPS", "2"))
BE_MAX_BPS              = float(os.getenv("BE_MAX_BPS", "25"))
SL_MONOTONIC            = os.getenv("SL_MONOTONIC", "1") in ("1","true","yes","on")
PROFIT_LOCK_STEPS       = [float(x) for x in (os.getenv("PROFIT_LOCK_STEPS", "1.0,1.5,2.0").split(","))]
ATR_UPDATE_COOLDOWN_SEC = int(os.getenv("ATR_UPDATE_COOLDOWN_SEC", "20"))
AUTO_TRAIL_ATRPCT_MAX   = float(os.getenv("AUTO_TRAIL_ATRPCT_MAX", "0.015"))
AUTO_TRAIL_ADX_MIN      = float(os.getenv("AUTO_TRAIL_ADX_MIN", "14"))

# ===== Live-Manage (NEW): Grace / BE triggers / Hysteresis =====
GRACE_ENABLE             = os.getenv("GRACE_ENABLE", "1").lower() in ("1","true","yes","on")
GRACE_TIME_SEC           = int(os.getenv("GRACE_TIME_SEC", "420"))              # 7min
GRACE_MAX_MAE_ATR        = float(os.getenv("GRACE_MAX_MAE_ATR", "1.2"))         # MAE cap = 1.2×ATR

BE_TRIGGER_REQUIRE_ADX   = float(os.getenv("BE_TRIGGER_REQUIRE_ADX", "22"))     # ADX gate
BE_TRIGGER_PROG_TO_TP1   = float(os.getenv("BE_TRIGGER_PROG_TO_TP1_PCT", "0.35"))  # 35% way to TP1
PROG_TO_TP1_FALLBACK_PCT = float(os.getenv("PROG_TO_TP1_FALLBACK_PCT", "0.60")) # 60% move of entry if no TP1

HYSTERESIS_ATR_FRAC      = float(os.getenv("HYSTERESIS_ATR_FRAC", "0.2"))       # need ≥ 0.2×ATR move to shift SL
SL_MIN_STEP_BPS          = float(os.getenv("SL_MIN_STEP_BPS", "3"))             # or ≥3bps absolute move on price

# ===== ConfirmStore =====
try:
    if not CONFIRMSTORE_ENABLE:
        raise RuntimeError("ConfirmStore disabled by env")
    from utils.trade_executor import ConfirmStore  # type: ignore
except Exception as e:
    logger.error("ConfirmStore unavailable (%s). Fallback disabled=%s", e, not CONFIRMSTORE_ENABLE)
    class _NoConfirm:
        @classmethod
        def pending(cls) -> List[Dict[str, Any]]: return []
        @classmethod
        def create(cls, payload: Dict[str, Any]) -> str: raise RuntimeError("ConfirmStore disabled")
        @classmethod
        def decide(cls, ticket_id: str, approved: bool) -> Dict[str, Any]:
            raise RuntimeError("ConfirmStore disabled")
        @classmethod
        def flush_all(cls) -> None: return None
    ConfirmStore = _NoConfirm  # type: ignore

# ===== Runtime State =====
TICK_COUNT: int = 0
LAST_TICK_TS: int = 0
LAST_CREATED: List[str] = []
LAST_PENDING: int = 0
LAST_ERROR: Optional[str] = None

# === WS runtime
_WS_TASK: Optional[asyncio.Task] = None
PRICE_MAP: Dict[str, float] = {}
LAST_PRICE_TS: Dict[str, float] = {}
AF_LAST_EVAL: Dict[str, float] = {}
AF_LAST_EVAL_PX: Dict[str, float] = {}
AF_LAST_FLIP: Dict[str, float] = {}

# === RT manage caches
_IND_LAST: Dict[str, Dict[str, float]] = {}     # {'ADX': float, 'ATR': float, 'CLOSE': float}
_IND_LAST_TS: Dict[str, float] = {}

# === Live per-symbol state (for GRACE/BE/SL monotonicity)
_LIVE: Dict[str, Dict[str, Any]] = {}  # {sym: {start_ts, entry, last_sl, armed_be, armed_time}}

# ===== Prometheus metrics =====
_PROM_PREFIX = "pos_live_manage"
POS_LIVE_DECISION = Counter(f"{_PROM_PREFIX}_decision_total",
                            "Live-manage decisions taken",
                            ["symbol","side","action"])  # action ∈ {grace_skip,grace_cap,be_armed,trail_move,lock_move}
POS_LIVE_ERRORS   = Counter(f"{_PROM_PREFIX}_errors_total",
                            "Live-manage errors",
                            ["symbol","where"])
POS_LIVE_SL_STEP  = Summary(f"{_PROM_PREFIX}_sl_step_abs",
                            "Observed absolute SL step size (price units)",
                            ["symbol","side","action"])
POS_LIVE_ATR_ABS  = Summary(f"{_PROM_PREFIX}_atr_abs",
                            "Observed absolute ATR (price units) during decisions",
                            ["symbol","side"])

def _bearer_ok(auth_header: Optional[str]) -> bool:
    if not API_BEARER_TOKEN:
        return True
    if not (auth_header and auth_header.startswith("Bearer ")):
        return False
    token = auth_header.split(" ", 1)[1].strip()
    return token == API_BEARER_TOKEN

def _entry_score_block_info(obj: Dict[str, Any]) -> Dict[str, float | bool | str]:
    try:
        min_req = float(os.getenv("ENTRY_SCORE_MIN", "0") or 0)
    except Exception:
        min_req = 0.0
    try:
        raw_score = obj.get("score", None)
        score = float(raw_score) if raw_score is not None else 0.0
    except Exception:
        score = 0.0
    blocked = (min_req > 0 and score < min_req)
    if blocked:
        badge = "⚠️ BLOCKED_BY_ENTRY_SCORE"
        line  = f"⚠️ blocked: score {score:.2f} < min {min_req:.2f}"
        severity = "warn"
    else:
        badge = "✅ ENTRY SCORE OK"
        line  = f"✅ entry score: {score:.2f}" if min_req == 0 else f"✅ entry score OK: {score:.2f} ≥ min {min_req:.2f}"
        severity = "ok"
    return {
        "blocked": bool(blocked),
        "score": float(score),
        "min_req": float(min_req),
        "badge": badge,
        "status_line": line,
        "severity": severity,
    }

def _ticket_id_for(obj: Dict[str, Any]) -> str:
    key = {
        "symbol": obj.get("symbol"),
        "market": obj.get("market","futures"),
        "timeframe": obj.get("timeframe", DEFAULT_TF),
        "side": obj.get("side"),
        "reason": obj.get("reason",""),
        "score": obj.get("score",0.0),
        "require_approval": bool(obj.get("require_approval", True)),
        "entry": obj.get("entry","limit"),
        "risk_pct": obj.get("risk_pct", 0.5),
        "stop_loss_pct": obj.get("stop_loss_pct", 0.8),
        "take_profit_rr": obj.get("take_profit_rr", 1.6),
    }
    h = hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()[:16]
    return f"TKT-{h}"

def _load_ingests() -> List[Dict[str, Any]]:
    if not INGEST_DIR.is_dir():
        return []
    items: List[Dict[str, Any]] = []
    for p in sorted(INGEST_DIR.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True):
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(obj, dict): items.append(obj)
            elif isinstance(obj, list): items.extend([x for x in obj if isinstance(x, dict)])
        except Exception as e:
            logger.warning("ingest read failed: %s (%s)", p, e)
    return items

def _get_pending_safe() -> List[Dict[str, Any]]:
    try:
        res = ConfirmStore.pending()  # type: ignore
        return [x for x in res if isinstance(x, dict)]
    except Exception:
        return []

def _already_pending(tid: str) -> bool:
    try:
        return any((x.get("ticket_id") == tid) for x in _get_pending_safe())
    except Exception:
        return False

def _auth_headers() -> Dict[str, str]:
    h = {"Accept": "application/json"}
    if API_TOKEN:
        h["x-api-key"] = API_TOKEN
    return h

async def _post_alerts_ingest(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not ALERTS_INGEST_URL or not PUBLIC_HOST:
        raise RuntimeError("ALERTS_INGEST_URL/PUBLIC_HOST not configured")
    async with observe_http_ctx_async(name="alerts_ingest"):
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as cli:
            r = await cli.post(ALERTS_INGEST_URL, json=payload, headers=_auth_headers())
            try:
                data = r.json()
            except Exception:
                data = {"status": r.status_code, "text": r.text}
            if r.status_code >= 400:
                raise RuntimeError(f"alerts_ingest_http_{r.status_code}: {data}")
            return data

def _build_ingest_payload(obj: Dict[str, Any]) -> Dict[str, Any]:
    symbol = str(obj.get("symbol","")).upper()
    side = str(obj.get("side","")).upper()
    qty = float(obj.get("qty") or DEFAULT_QTY)
    leverage = int(obj.get("leverage") or DEFAULT_LEVERAGE)
    require_approval = bool(obj.get("require_approval", True))
    reason = obj.get("reason","")
    try:
        score = float(obj.get("score", 0.0) or 0.0)
    except Exception:
        score = 0.0
    es = _entry_score_block_info(obj)
    payload: Dict[str, Any] = {
        "ticket_id": _ticket_id_for(obj),
        "symbol": symbol,
        "market": str(obj.get("market","futures")).lower(),
        "side": side,
        "qty": qty,
        "leverage": leverage,
        "score": score,
        "reason": reason,
        "require_approval": require_approval,
        "timeframe": obj.get("timeframe", DEFAULT_TF),
        "tp1": obj.get("tp1"),
        "tp2": obj.get("tp2"),
        "tp3": obj.get("tp3"),
        "sl": obj.get("sl"),
        "blocked_by_entry_score": bool(es["blocked"]),
        "entry_score": float(es["score"]),
        "entry_score_min": float(es["min_req"]),
    }
    for k in ["prob_overall_pct","prob_tp1_pct","prob_tp2_pct","prob_tp3_pct",
              "eta_open_min","eta_tp1_min","eta_tp2_min","eta_tp3_min","expiry_ts","tp_splits","position_side","note",
              "entry_price","price","approve_url","reject_url","ticket_url","budget_usd","ttl_sec"]:
        if obj.get(k) is not None:
            payload[k] = obj.get(k)
    if not symbol or side not in ("BUY","SELL"):
        raise ValueError("bad symbol/side in ingest payload")
    if qty <= 0 or leverage <= 0:
        raise ValueError("qty/leverage must be > 0 for alerts/ingest")
    return payload

async def _notify_telegram_approval_from_obj(obj: Dict[str, Any], ticket_id: str) -> None:
    es = _entry_score_block_info(obj)
    symbol = str(obj.get("symbol","")).upper()
    side   = str(obj.get("side","")).upper()
    leverage = obj.get("leverage") or DEFAULT_LEVERAGE
    tp_legs = []
    for i in (1,2,3):
        v = obj.get(f"tp{i}")
        if v is None:
            continue
        try:
            tp_legs.append({"stopPrice": float(v), "split": obj.get("tp_splits", [0.4,0.35,0.25])[i-1] if isinstance(obj.get("tp_splits"), list) else None})
        except Exception:
            pass
    sl_px = obj.get("sl")
    sl_obj = {"stopPrice": float(sl_px)} if sl_px is not None else {}
    probs = {
        "overall": obj.get("prob_overall_pct"),
        "tp1": obj.get("prob_tp1_pct"),
        "tp2": obj.get("prob_tp2_pct"),
        "tp3": obj.get("prob_tp3_pct"),
    }
    eta = {
        "entry_sec": (obj.get("eta_open_min") or 0) * 60 if obj.get("eta_open_min") is not None else None,
        "tp1_sec": (obj.get("eta_tp1_min") or 0) * 60 if obj.get("eta_tp1_min") is not None else None,
        "tp2_sec": (obj.get("eta_tp2_min") or 0) * 60 if obj.get("eta_tp2_min") is not None else None,
        "tp3_sec": (obj.get("eta_tp3_min") or 0) * 60 if obj.get("eta_tp3_min") is not None else None,
    }
    base_why = (obj.get("reason") or "")
    why = f"{es['status_line']} | {base_why}".strip(" |") if es["status_line"] else base_why
    plan: Dict[str, Any] = {
        "symbol": symbol,
        "side": side,
        "leverage": leverage,
        "order_type": "MARKET",
        "entry_price": obj.get("entry_price") or obj.get("price"),
        "sl": sl_obj,
        "tp": tp_legs,
        "timeframe": obj.get("timeframe", DEFAULT_TF),
        "why": why,
        "score": float(obj.get("score",0.0) or 0.0),
        "blocked_by_entry_score": bool(es["blocked"]),
        "entry_score": float(es["score"]),
        "entry_score_min": float(es["min_req"]),
        "badges": [str(es["badge"])],
        "entry_score_status_line": str(es["status_line"]),
        "severity": str(es["severity"]),
        "probs": probs,
        "eta": eta,
        "trade_kind": obj.get("market","futures"),
        "budget_usd": obj.get("budget_usd"),
        "approve_url": obj.get("approve_url"),
        "reject_url": obj.get("reject_url"),
        "ticket_url": obj.get("ticket_url"),
        "require_approval": obj.get("require_approval", True),
        "ttl_sec": int(obj.get("ttl_sec") or 600),
    }
    try:
        await send_trade_approval(ticket_id, plan, chat_id=None)
    except Exception as e:
        logger.warning("telegram approval notify failed: %s", e)

def _create_ticket_fallback(obj: Dict[str, Any]) -> Optional[str]:
    if not CONFIRMSTORE_ENABLE:
        return None
    if not obj.get("symbol") or not obj.get("side"):
        return None
    payload = {
        "ticket_id": _ticket_id_for(obj),
        "source": obj.get("source","ingest"),
        "symbol": obj.get("symbol"),
        "market": obj.get("market","futures"),
        "timeframe": obj.get("timeframe", DEFAULT_TF),
        "side": obj.get("side"),
        "score": float(obj.get("score", 0.0)) if obj.get("score") is not None else None,
        "reason": obj.get("reason",""),
        "entry_mode": obj.get("entry","limit"),
        "risk_pct": float(obj.get("risk_pct", 0.5)),
        "stop_loss_pct": float(obj.get("stop_loss_pct", 0.8)),
        "take_profit_rr": float(obj.get("take_profit_rr", 1.6)),
        "require_approval": bool(obj.get("require_approval", True)),
        "ts": int(time.time()),
    }
    tid = payload["ticket_id"]
    if _already_pending(tid):
        return None
    try:
        return ConfirmStore.create(payload) or tid  # type: ignore
    except Exception as e:
        logger.error("ConfirmStore.create failed: %s", e)
        return None

async def _dispatch_signal(obj: Dict[str, Any]) -> Optional[str]:
    tid = _ticket_id_for(obj)
    if _already_pending(tid):
        return None
    can_network = bool(PUBLIC_HOST and ALERTS_INGEST_URL)
    if can_network:
        try:
            payload = _build_ingest_payload(obj)
            resp = await _post_alerts_ingest(payload)
            logger.info("alerts/ingest ok: %s", resp)
            await _notify_telegram_approval_from_obj(obj, ticket_id=payload["ticket_id"])
            return tid
        except Exception as e:
            logger.warning("alerts/ingest failed (%s) — fallback ConfirmStore", e)
    tid_fb = _create_ticket_fallback(obj)
    if tid_fb:
        await _notify_telegram_approval_from_obj(obj, ticket_id=tid_fb)
    return tid_fb

# ---------- Public endpoints (כמו קודם, ללא שינויי API) ----------
class TradeOpenRequest(BaseModel):
    symbol: str
    side: str  # BUY | SELL
    qty: float
    entry_price: Optional[float] = None
    sl_price: Optional[float] = None
    tp_price: Optional[float] = None
    leverage: int = 10
    position_side: str = "BOTH"
    time_stop_sec: Optional[int] = None
    meta: Optional[Dict[str, Any]] = None

@router.post("/manager/open")
async def manager_open(req: TradeOpenRequest) -> Dict[str, Any]:
    if not _STATE_MACHINE_AVAILABLE:
        raise HTTPException(status_code=501, detail="StateMachine not available (utils.open_trade_manager_state.py missing)")
    try:
        plan = TradePlan(  # type: ignore[call-arg]
            symbol=req.symbol.upper(),
            side=req.side.upper(),
            qty=float(req.qty),
            entry_price=req.entry_price,
            sl_price=req.sl_price,
            tp_price=req.tp_price,
            leverage=int(req.leverage),
            position_side=req.position_side.upper(),
            time_stop_sec=req.time_stop_sec,
            meta=req.meta or {},
        )
        mgr = TradeStateManager(plan)  # type: ignore[call-arg]
        res = await asyncio.get_running_loop().run_in_executor(None, mgr.run_once)
        if not isinstance(res, dict):
            res = {"ok": True, "result": res}
        res.setdefault("state_available", True)
        return res
    except Exception as e:
        logger.exception("manager_open failed")
        raise HTTPException(status_code=500, detail={"ok": False, "error": str(e)})

@router.post("/ops/manager/tick")
async def ops_manager_tick():
    return await _tick_once()

@router.get("/ops/manager/health")
async def ops_manager_health():
    return {
        "ok": True,
        "enabled": MANAGER_ENABLE,
        "interval_sec": MANAGER_INTERVAL_SEC,
        "ingest_dir": str(INGEST_DIR),
        "last_tick_ts": LAST_TICK_TS,
        "tick_count": TICK_COUNT,
        "created_last": LAST_CREATED,
        "pending_count": LAST_PENDING,
        **({"errors_last": LAST_ERROR} if LAST_ERROR else {}),
        "alerts_ingest_url": ALERTS_INGEST_URL or None,
        "public_host": PUBLIC_HOST or None,
        "state_machine": _STATE_MACHINE_AVAILABLE,
        "writes_orders": MANAGER_WRITES_ORDERS,
        "native_tpsl_enable": NATIVE_TPSL_ENABLE,
        "order_trigger": ORDER_TRIGGER,
        "auto_flip_enable": AUTO_FLIP_ENABLE,
        "ws_autoflip": bool(USE_WS and AUTO_FLIP_ENABLE),
        "rt_manage": bool(TRAIL_RT_ENABLE),
    }

@router.get("/alerts/trades/active")
async def alerts_trades_active():
    try:
        items = _get_pending_safe()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"ConfirmStore error: {e}")
    out: Dict[str, Any] = {}
    for it in items:
        tid = it.get("ticket_id") or _ticket_id_for(it)
        out[tid] = it
    return {"ok": True, "count": len(out), "items": out}

class UpdateTicketReq(BaseModel):
    ticket_id: str
    action: str  # APPROVE | REJECT

@router.post("/alerts/trades/update")
async def alerts_trades_update(
    req: UpdateTicketReq,
    x_timestamp: Optional[str] = Header(None, alias="X-Timestamp"),
    x_nonce: Optional[str]   = Header(None, alias="X-Nonce"),
    x_signature: Optional[str]= Header(None, alias="X-Signature"),
):
    ok, why = verify_request(
        ts_header=x_timestamp,
        nonce_header=x_nonce,
        signature_header=x_signature,
        route="/alerts/trades/update",
        body=req.dict(),
        require_signature=ANTI_REPLAY_REQUIRE_SIGNATURE,
    )
    if not ok:
        raise HTTPException(status_code=400, detail=f"anti_replay_failed: {why}")

    act = req.action.upper().strip()
    if act not in ("APPROVE","REJECT"):
        raise HTTPException(status_code=400, detail="action must be APPROVE or REJECT")
    try:
        res = ConfirmStore.decide(req.ticket_id, approved=(act=="APPROVE"))  # type: ignore
        return {"ok": True, "result": res}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"decision failed: {e}")

class ManageOnceReq(BaseModel):
    symbol: Optional[str] = None
    offset_bps: Optional[int] = None
    pcts: Optional[List[float]] = None
    splits: Optional[List[float]] = None
    atr_mult: Optional[float] = None
    write_orders: Optional[bool] = None
    force_rewrite: Optional[bool] = None

@router.post("/manage-once-lite")
async def manage_once_lite(
    req: ManageOnceReq = Body(...),
    authorization: Optional[str] = Header(None, alias="Authorization"),
) -> Dict[str, Any]:
    if not _bearer_ok(authorization):
        raise HTTPException(status_code=401, detail="Unauthorized")

    payload: Dict[str, Any] = {k: v for k, v in req.dict().items() if v is not None}
    write_orders = payload.pop("write_orders", None)
    if write_orders is None:
        write_orders = MANAGER_WRITES_ORDERS
    force_rewrite = payload.pop("force_rewrite", False)

    if position_ops_manage_once is not None:
        try:
            res = await position_ops_manage_once({**payload, "write_orders": bool(write_orders), "force_rewrite": bool(force_rewrite)})  # type: ignore
            return {"ok": True, "delegated": True, "result": res, "writer": "routes.position_ops.manage_once"}
        except Exception as e:
            logger.warning("routes.position_ops.manage_once failed: %s", e)

    if pm_manage_once is not None:
        try:
            res = await pm_manage_once(**{**payload, "write_orders": bool(write_orders), "force_rewrite": bool(force_rewrite)})  # type: ignore
            return {"ok": True, "delegated": True, "result": res, "writer": "utils.position_manager.manage_once"}
        except Exception as e:
            logger.warning("utils.position_manager.manage_once failed: %s", e)

    if not TradeClient:
        return {"ok": True, "delegated": False, "skipped": True, "reason": "manager_not_available_and_no_trade_client"}

    plan = {
        "be_bps": PROFILE_BASE_BE_BPS,
        "tp_pcts": SMART_MANAGE_PCTS,
        "tp_splits": SMART_MANAGE_SPLITS,
        "trail_atr_mult": TRAIL_ATR_MULT,
        "trigger": ORDER_TRIGGER,
    }
    return {"ok": True, "delegated": False, "plan_only": plan, "reason": "fallback_no_writer"}

class SymbolReq(BaseModel):
    symbol: str

async def _do_rewrite_native_tpsl(symbol: str) -> Dict[str, Any]:
    sym = symbol.upper().strip()
    if position_ops_rewrite_native_tpsl is not None:
        try:
            res = await position_ops_rewrite_native_tpsl({"symbol": sym})  # type: ignore
            return {"ok": True, "delegated": True, "result": res, "writer": "routes.position_ops.rewrite_native_tpsl"}
        except Exception as e:
            logger.warning("routes.position_ops.rewrite_native_tpsl failed: %s", e)

    if pm_rewrite_native_tpsl is not None:
        try:
            res = await pm_rewrite_native_tpsl(symbol=sym)  # type: ignore
            return {"ok": True, "delegated": True, "result": res, "writer": "utils.position_manager.rewrite_native_tpsl"}
        except Exception as e:
            logger.warning("utils.position_manager.rewrite_native_tpsl failed: %s", e)

    if TradeClient:
        try:
            cli = TradeClient()  # type: ignore
            pos = await cli.get_position(sym)  # type: ignore
            if not pos or float(pos.get("positionAmt") or 0.0) == 0.0:
                return {"ok": False, "error": "no_active_position"}
            await cli.cancel_all_reduce_only(sym)  # type: ignore
            entry = float(pos.get("entryPrice") or 0.0)
            side  = "BUY" if float(pos.get("positionAmt", 0)) > 0 else "SELL"
            tp_pcts = SMART_MANAGE_PCTS
            splits  = SMART_MANAGE_SPLITS
            be_bps = PROFILE_BASE_BE_BPS
            be_price = entry * (1.0 + (be_bps/10000.0) * (1 if side=="BUY" else -1))
            await cli.place_stop_loss_or_be(sym, side, be_price, trigger=ORDER_TRIGGER)  # type: ignore
            for i, pct in enumerate(tp_pcts, start=1):
                tp_price = entry * (1.0 + (pct/100.0) * (1 if side=="BUY" else -1))
                qty_split = splits[i-1] if i-1 < len(splits) else None
                await cli.place_take_profit(sym, side, tp_price, split=qty_split, idx=i, trigger=ORDER_TRIGGER)  # type: ignore
            return {"ok": True, "delegated": False, "writer": "fallback_trade_client", "be_bps": be_bps, "tp_pcts": tp_pcts}
        except Exception as e:
            return {"ok": False, "error": f"fallback_trade_client_failed: {e}"}

    return {"ok": False, "error": "no_rewriter_available"}

@router.post("/manager/rewrite-native-tpsl")
async def manager_rewrite_native_tpsl(
    req: SymbolReq,
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    if not _bearer_ok(authorization):
        raise HTTPException(status_code=401, detail="Unauthorized")
    if not NATIVE_TPSL_ENABLE:
        raise HTTPException(status_code=400, detail="NATIVE_TPSL_ENABLE=0")
    return await _do_rewrite_native_tpsl(req.symbol)

@router.post("/trade/sync-native-tpsl")
async def trade_sync_native_tpsl(
    req: SymbolReq,
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    if not _bearer_ok(authorization):
        raise HTTPException(status_code=401, detail="Unauthorized")
    if not NATIVE_TPSL_ENABLE:
        raise HTTPException(status_code=400, detail="NATIVE_TPSL_ENABLE=0")
    return await _do_rewrite_native_tpsl(req.symbol)

# --- Webhook אירועי ביצוע/TP/SL (כמו קודם) ---
class ExecEvent(BaseModel):
    symbol: str
    event: Optional[str] = None
    idx: Optional[int] = None
    price: Optional[float] = None
    qty: Optional[float] = None
    frm: Optional[float] = None
    to: Optional[float] = None
    raw: Optional[Dict[str, Any]] = None

@router.post("/events/execution")
async def events_execution(ev: ExecEvent):
    sym = ev.symbol.upper()
    if ev.event:
        try:
            if ev.event == "tp_hit":
                idx = int(ev.idx or 0)
                await emit(sym, f"tp{idx}_hit", price=float(ev.price or 0.0), filled_qty=float(ev.qty or 0.0))
                return {"ok": True, "emitted": f"tp{idx}_hit"}
            elif ev.event == "be_move":
                await emit(sym, "be_move", frm=(float(ev.frm) if ev.frm is not None else None), to=float(ev.to or 0.0))
                return {"ok": True, "emitted": "be_move"}
            elif ev.event == "sl_move":
                await emit(sym, "sl_move", frm=(float(ev.frm) if ev.frm is not None else None), to=float(ev.to or 0.0))
                return {"ok": True, "emitted": "sl_move"}
            elif ev.event == "sl_hit":
                await emit(sym, "sl_hit", price=float(ev.price or 0.0))
                return {"ok": True, "emitted": "sl_hit"}
            else:
                extra = {k: v for k, v in {"idx": ev.idx, "price": ev.price, "qty": ev.qty, "frm": ev.frm, "to": ev.to}.items() if v is not None}
                await emit(sym, ev.event, **extra)
                return {"ok": True, "emitted": ev.event}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"emit_failed: {e}")

    raw = ev.raw or {}
    try:
        etype = str(raw.get("e") or raw.get("eventType") or "").upper()
        if etype == "EXECUTION_REPORT":
            otype = str(raw.get("o") or raw.get("orderType") or "").upper()
            status = str(raw.get("X") or raw.get("orderStatus") or "").upper()
            side = str(raw.get("S") or raw.get("side") or "").upper()
            client_id = str(raw.get("c") or raw.get("clientOrderId") or "")
            reduce_only = str(raw.get("reduceOnly") or raw.get("R") or "").lower() == "true"
            filled_qty = float(raw.get("z") or raw.get("filledQty") or 0.0)
            last_price = float(raw.get("L") or raw.get("lastPrice") or 0.0)

            if otype == "LIMIT" and reduce_only and status in ("FILLED", "PARTIALLY_FILLED", "TRADE"):
                idx = 0
                up = client_id.upper()
                for i in (1,2,3,4):
                    if f"TP{i}" in up: idx = i; break
                await emit(sym, f"tp{idx}_hit", price=last_price, filled_qty=filled_qty, side=side, coid=client_id)
                return {"ok": True, "emitted": f"tp{idx}_hit"}

            if otype in ("STOP", "STOP_MARKET") and status in ("FILLED", "TRADE"):
                await emit(sym, "sl_hit", price=last_price, side=side, coid=client_id)
                return {"ok": True, "emitted": "sl_hit"}

        await emit(sym, "note", raw=raw)
        return {"ok": True, "emitted": "note"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"exec_event_parse_failed: {e}")

# =================== Tick (fallback) ===================
async def _tick_once() -> Dict[str, Any]:
    global TICK_COUNT, LAST_TICK_TS, LAST_CREATED, LAST_PENDING, LAST_ERROR
    created: List[str] = []
    LAST_ERROR = None
    try:
        for obj in _load_ingests():
            tid = await _dispatch_signal(obj)
            if tid:
                created.append(tid)

        # ניהול תקופתי קל (Fallback) + אוטופליפ
        if MANAGER_WRITES_ORDERS and (pm_manage_once or position_ops_manage_once):
            symbols: List[str] = []
            if get_positions_snapshot:
                try:
                    snap = await get_positions_snapshot()
                    for row in (snap or []):
                        sym = str(row.get("symbol") or "").upper()
                        amt = float(row.get("positionAmt") or 0.0)
                        if sym and abs(amt) > 0.0:
                            symbols.append(sym)
                except Exception as e:
                    logger.debug("get_positions_snapshot failed: %s", e)
            for sym in symbols:
                try:
                    if position_ops_manage_once:
                        await position_ops_manage_once({"symbol": sym, "write_orders": True, "force_rewrite": False})  # type: ignore
                    elif pm_manage_once:
                        await pm_manage_once(symbol=sym, write_orders=True, force_rewrite=False)  # type: ignore
                except Exception as e:
                    logger.debug("periodic manage_once for %s failed: %s", sym, e)

        # Auto-Flip (tick path) — רק אם WS לא פעיל
        if AUTO_FLIP_ENABLE and get_positions_snapshot and not (USE_WS and _WS_TASK and not _WS_TASK.done()):
            try:
                snap = await get_positions_snapshot()
                for row in (snap or []):
                    sym = str(row.get("symbol") or "").upper()
                    amt = float(row.get("positionAmt") or 0.0)
                    if not sym or abs(amt) == 0.0:
                        continue
                    side_now = "BUY" if amt > 0 else "SELL"
                    desired = None
                    if eval_regime:
                        try:
                            reg = await eval_regime(symbol=sym, long_req=LONG_REQ, short_req=SHORT_REQ, neutral_req=NEUTRAL_REQ, timeframe=DEFAULT_TF)  # type: ignore
                            want = str(reg.get("want","")).upper()
                            if want == "LONG":  desired = "BUY"
                            elif want == "SHORT": desired = "SELL"
                            elif AUTO_FLIP_NEUTRAL:
                                desired = "NEUTRAL"
                        except Exception as e:
                            logger.debug("eval_regime failed (tick) for %s: %s", sym, e)
                    if desired and desired != side_now:
                        try:
                            if TradeClient:
                                cli = TradeClient()  # type: ignore
                                await cli.close_position_market(sym)  # type: ignore
                                if desired in ("BUY","SELL"):
                                    qty = abs(amt) or DEFAULT_QTY
                                    await cli.open_market(sym, desired, qty=qty, leverage=DEFAULT_LEVERAGE)  # type: ignore
                                await emit(sym, "auto_flip", from_side=side_now, to=desired)
                        except Exception as e:
                            logger.debug("auto_flip (tick) %s failed: %s", sym, e)

        pend = _get_pending_safe()
        TICK_COUNT += 1
        LAST_TICK_TS = int(time.time())
        LAST_CREATED = created
        LAST_PENDING = len(pend)
        return {"ok": True, "created": created, "pending_count": len(pend)}
    except Exception as e:
        LAST_ERROR = str(e)
        logger.error("tick error: %s", e)
        return {"ok": False, "error": str(e), "created": created}

# =================== RT Manage helpers ===================
async def _refresh_indicators(symbol: str) -> Tuple[float, float, float]:
    """
    מחזיר (close, atr, adx). ממוזער בבקשות: רק אם עבר ATR_UPDATE_COOLDOWN_SEC.
    """
    now = time.time()
    last_ts = _IND_LAST_TS.get(symbol, 0.0)
    if now - last_ts < ATR_UPDATE_COOLDOWN_SEC:
        d = _IND_LAST.get(symbol, {})
        return d.get("CLOSE", float("nan")), d.get("ATR", float("nan")), d.get("ADX", float("nan"))

    base = os.getenv("BINANCE_FAPI", "https://fapi.binance.com").rstrip("/")
    tf = os.getenv("DEFAULT_INTERVAL", DEFAULT_TF)
    url = f"{base}/fapi/v1/klines"
    params = {"symbol": symbol.upper(), "interval": tf, "limit": 200}
    try:
        async with httpx.AsyncClient(timeout=8.0) as cli:
            r = await cli.get(url, params=params)
            r.raise_for_status()
            kl = r.json()
    except Exception as e:
        logger.debug("refresh_indicators http failed for %s: %s", symbol, e)
        d = _IND_LAST.get(symbol, {})
        return d.get("CLOSE", float("nan")), d.get("ATR", float("nan")), d.get("ADX", float("nan"))

    if not kl or len(kl) < 20:
        d = _IND_LAST.get(symbol, {})
        return d.get("CLOSE", float("nan")), d.get("ATR", float("nan")), d.get("ADX", float("nan"))

    import pandas as pd  # local import to keep top clean
    close = pd.Series([float(x[4]) for x in kl], dtype=float)
    high  = pd.Series([float(x[2]) for x in kl], dtype=float)
    low   = pd.Series([float(x[3]) for x in kl], dtype=float)
    last_close = float(close.iloc[-1])

    _atr = float(atr(pd.DataFrame({"high":high,"low":low,"close":close}), 14).iloc[-1]) if atr else float("nan")  # type: ignore
    _adx = float(adx(pd.DataFrame({"high":high,"low":low,"close":close}), 14).iloc[-1]) if adx else float("nan")  # type: ignore

    _IND_LAST[symbol] = {"CLOSE": last_close, "ATR": _atr, "ADX": _adx}
    _IND_LAST_TS[symbol] = now
    return last_close, _atr, _adx

def _should_eval(symbol: str, price: float, now_ts: float) -> bool:
    last_ts = AF_LAST_EVAL.get(symbol, 0.0)
    if now_ts - last_ts < AF_EVAL_COOLDOWN_SEC:
        return False
    prev_px = AF_LAST_EVAL_PX.get(symbol, 0.0)
    if prev_px > 0:
        delta_bps = abs(price - prev_px) / prev_px * 10000.0
        if delta_bps < AF_MOVE_TRIGGER_BPS:
            return False
    return True

def _flip_cooldown_ok(symbol: str, now_ts: float) -> bool:
    lt = AF_LAST_FLIP.get(symbol, 0.0)
    return (now_ts - lt) >= AF_FLIP_COOLDOWN_SEC

def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))

def _bps_to_abs(bps: float, price: float) -> float:
    return abs(bps) / 10000.0 * max(price, 1e-9)

def _hysteresis_ok(prev_sl: Optional[float], new_sl: float, atr_abs: float, ref_price: float, side: str) -> bool:
    """
    תנאי הזזה: (1) מונוטוניות (אם מופעל), (2) שינוי מספיק: max(HYSTERESIS_ATR_FRAC×ATR, SL_MIN_STEP_BPS in abs).
    """
    if prev_sl is None or not math.isfinite(prev_sl):
        return True
    if SL_MONOTONIC:
        if side == "BUY" and new_sl < prev_sl:
            return False
        if side == "SELL" and new_sl > prev_sl:
            return False
    step_abs = max(HYSTERESIS_ATR_FRAC * max(atr_abs, 0.0), _bps_to_abs(SL_MIN_STEP_BPS, ref_price))
    return abs(new_sl - prev_sl) >= step_abs

def _tp1_price(entry: float, side: str) -> Optional[float]:
    try:
        pct = SMART_MANAGE_PCTS[0]
    except Exception:
        return None
    sign = 1.0 if side == "BUY" else -1.0
    return entry * (1.0 + (pct/100.0) * sign)

# =================== RT Manage core (WS) ===================
async def _rt_manage(symbol: str) -> None:
    """
    ניהול “חי” ל-SL/TP: חלון GRACE, BE חכם (ADX+Progress), טרייל ATR + נעילות רווח, היסטרזיס ומונוטוניות.
    """
    if not (TRAIL_RT_ENABLE and TradeClient and get_positions_snapshot):
        return
    price = PRICE_MAP.get(symbol)
    ts = LAST_PRICE_TS.get(symbol, 0.0)
    now_ts = time.time()
    if not price or now_ts - ts > AF_PRICE_TTL_SEC:
        return

    # מצב פוזיציה
    pos_amt = 0.0
    entry = None
    side_now = None
    try:
        snap = await get_positions_snapshot()
        for row in (snap or []):
            if str(row.get("symbol","")).upper() == symbol:
                pos_amt = float(row.get("positionAmt") or 0.0)
                if pos_amt != 0.0:
                    entry = float(row.get("entryPrice") or 0.0)
                    side_now = "BUY" if pos_amt > 0 else "SELL"
                break
    except Exception:
        return
    if not side_now or not entry or entry <= 0:
        return

    # אינדיקטורים עדכניים/קאש
    last_close, _atr, _adx = await _refresh_indicators(symbol)
    if not (math.isfinite(_atr) and _atr >= 0.0 and math.isfinite(_adx)):
        _atr = 0.0
        _adx = 0.0
    atr_abs = float(_atr)
    try:
        POS_LIVE_ATR_ABS.labels(symbol, side_now).observe(max(0.0, atr_abs))
    except Exception:
        pass

    # סטייט מקומי לניהול חי
    st = _LIVE.setdefault(symbol, {"start_ts": now_ts, "entry": float(entry), "last_sl": None, "armed_be": False, "armed_time": None})
    if st.get("entry") != float(entry):
        # אם התחלף Entry (סגירה/פתיחה חדשה) — נאתחל GRACE וסטייט
        st.update({"start_ts": now_ts, "entry": float(entry), "last_sl": None, "armed_be": False, "armed_time": None})

    cli = TradeClient()  # type: ignore
    sign = 1.0 if side_now == "BUY" else -1.0

    # === GRACE: חלון חסד מוגבל MAE/ATR — לפני BE
    if GRACE_ENABLE and not st.get("armed_be", False):
        in_time = (now_ts - float(st["start_ts"])) <= GRACE_TIME_SEC
        mae_abs = max(0.0, (entry - price) if side_now == "BUY" else (price - entry))
        ok_mae = (atr_abs <= 0.0) or (mae_abs <= GRACE_MAX_MAE_ATR * atr_abs)
        if in_time and ok_mae:
            logging.debug("live-manage[%s] GRACE skip: in_time=%s mae=%.6f atr=%.6f cap=%.6f",
                          symbol, in_time, mae_abs, atr_abs, GRACE_MAX_MAE_ATR*atr_abs)
            try: POS_LIVE_DECISION.labels(symbol, side_now, "grace_skip").inc()
            except Exception: pass
            return
        if in_time and not ok_mae and atr_abs > 0.0:
            # חריגה: SL בקצה תקרת החסד (לא חוצה את המחיר הנוכחי)
            cap_sl = (entry - GRACE_MAX_MAE_ATR * atr_abs) if side_now == "BUY" else (entry + GRACE_MAX_MAE_ATR * atr_abs)
            cap_sl = min(cap_sl, price) if side_now == "BUY" else max(cap_sl, price)
            if _hysteresis_ok(st.get("last_sl"), cap_sl, atr_abs, price, side_now):
                await cli.place_stop_loss_or_be(symbol, side_now, float(cap_sl), trigger=ORDER_TRIGGER)  # type: ignore
                logging.info("live-manage[%s] GRACE cap -> SL=%.6f (entry=%.6f last=%.6f atr=%.6f)",
                             symbol, cap_sl, entry, price, atr_abs)
                prev = st.get("last_sl") or cap_sl
                st["last_sl"] = cap_sl
                try:
                    POS_LIVE_DECISION.labels(symbol, side_now, "grace_cap").inc()
                    POS_LIVE_SL_STEP.labels(symbol, side_now, "grace_cap").observe(abs(prev - cap_sl))
                except Exception: pass
            return  # אחרי cap ב-GRACE — לא מתקדם לשאר לוגיקה באותו טיק

    # === BE Trigger: דורש ADX ומידת התקדמות ל-TP1 (או fallback)
    want_be = (_adx >= BE_TRIGGER_REQUIRE_ADX)
    tp1 = _tp1_price(entry, side_now)
    if tp1 and tp1 != entry:
        numer = max(0.0, (price - entry) * sign)
        denom = abs(tp1 - entry)
        prog = numer / max(denom, 1e-9)
        want_be = want_be and (prog >= BE_TRIGGER_PROG_TO_TP1)
    else:
        # אין TP1 מוגדר → נבחן תנועה יחסית למחיר כניסה
        move_pct = max(0.0, (price - entry) * sign) / max(entry, 1e-9)
        want_be = want_be and (move_pct >= PROG_TO_TP1_FALLBACK_PCT)

    if want_be and not st.get("armed_be", False):
        be_bps = PROFILE_BASE_BE_BPS  # בסיס BE; ההטיה ל-TP כבר מגולמת בטריגר ולא במחיר ה-BE
        be_px = entry * (1.0 + (be_bps/10000.0) * sign)
        if _hysteresis_ok(st.get("last_sl"), be_px, atr_abs, price, side_now):
            await cli.place_stop_loss_or_be(symbol, side_now, float(be_px), trigger=ORDER_TRIGGER)  # type: ignore
            logging.info("live-manage[%s] BE armed -> SL=%.6f (adx=%.2f entry=%.6f last=%.6f)",
                         symbol, be_px, _adx, entry, price)
            prev = st.get("last_sl") or be_px
            st["last_sl"] = be_px
            st["armed_be"] = True
            st["armed_time"] = now_ts
            try:
                POS_LIVE_DECISION.labels(symbol, side_now, "be_armed").inc()
                POS_LIVE_SL_STEP.labels(symbol, side_now, "be_armed").observe(abs(prev - be_px))
            except Exception: pass
        # לאחר זריעת BE — נצא מהטיק כדי לא לערבב עם טרייל מיידי באותו רגע
        return

    # === Trail / Profit Locks — רק אחרי BE
    if st.get("armed_be", False):
        targets: List[float] = []

        # Trail ATR — רק אם תנאי ADX/ATR% מאפשרים (סינון רעשים)
        if atr_abs > 0.0 and _adx >= max(AUTO_TRAIL_ADX_MIN, BE_TRIGGER_REQUIRE_ADX) and ((atr_abs / max(price,1e-9)) <= AUTO_TRAIL_ATRPCT_MAX):
            trail = price - (TRAIL_RT_ATR_MULT * atr_abs) if side_now == "BUY" else price + (TRAIL_RT_ATR_MULT * atr_abs)
            # אל תוריד מתחת/מעל ל-BE (entry)
            trail = max(trail, entry) if side_now == "BUY" else min(trail, entry)
            targets.append(trail)

        # Profit locks — מדרגות multiples של ATR
        if atr_abs > 0.0 and PROFIT_LOCK_STEPS:
            profit_atr = (price - entry) * sign / max(atr_abs, 1e-9)
            lock_price = None
            for step in sorted(PROFIT_LOCK_STEPS):
                if profit_atr >= step:
                    lock_off = 0.25 * atr_abs * step
                    lp = entry + sign * lock_off
                    lock_price = lp if lock_price is None else (max(lock_price, lp) if side_now == "BUY" else min(lock_price, lp))
            if lock_price is not None:
                targets.append(lock_price)

        if not targets:
            return

        target_sl = max(targets) if side_now == "BUY" else min(targets)
        prev = st.get("last_sl")
        if _hysteresis_ok(prev, target_sl, atr_abs, price, side_now):
            try:
                await cli.place_stop_loss_or_be(symbol, side_now, float(target_sl), trigger=ORDER_TRIGGER)  # type: ignore
                st["last_sl"] = float(target_sl)
                logging.debug("live-manage[%s] SL move -> SL=%.6f (atr=%.6f last=%.6f)", symbol, target_sl, atr_abs, price)
                try:
                    POS_LIVE_DECISION.labels(symbol, side_now, "trail_move").inc()
                    POS_LIVE_SL_STEP.labels(symbol, side_now, "trail_move").observe(abs((prev or target_sl) - target_sl))
                except Exception: pass
                await emit(symbol, "sl_move", frm=(float(prev) if prev is not None else None), to=float(target_sl))
            except Exception as e:
                logging.debug("rt_manage(%s) place SL failed: %s", symbol, e)
                try:
                    POS_LIVE_ERRORS.labels(symbol, "rt_manage_place").inc()
                except Exception:
                    pass

async def _maybe_eval_and_flip(symbol: str) -> None:
    if not (AUTO_FLIP_ENABLE and eval_regime and TradeClient):
        return
    price = PRICE_MAP.get(symbol)
    ts = LAST_PRICE_TS.get(symbol, 0.0)
    now_ts = time.time()
    if not price or now_ts - ts > AF_PRICE_TTL_SEC:
        return
    if not _should_eval(symbol, price, now_ts):
        return
    try:
        reg = await eval_regime(symbol=symbol, long_req=LONG_REQ, short_req=SHORT_REQ, neutral_req=NEUTRAL_REQ, timeframe=DEFAULT_TF)  # type: ignore
    except Exception as e:
        logger.debug("eval_regime (ws) failed for %s: %s", symbol, e)
        return
    want = str(reg.get("want","")).upper()
    AF_LAST_EVAL[symbol] = now_ts
    AF_LAST_EVAL_PX[symbol] = price

    side_now = None
    amt = 0.0
    try:
        if get_positions_snapshot:
            snap = await get_positions_snapshot()
            for row in (snap or []):
                if str(row.get("symbol","")).upper() == symbol:
                    amt = float(row.get("positionAmt") or 0.0)
                    side_now = ("BUY" if amt > 0 else "SELL") if amt != 0 else None
                    break
    except Exception:
        pass

    desired = None
    if want == "LONG":  desired = "BUY"
    elif want == "SHORT": desired = "SELL"
    elif AUTO_FLIP_NEUTRAL:
        desired = "NEUTRAL"

    if not desired or desired == side_now:
        return
    if not _flip_cooldown_ok(symbol, now_ts):
        return

    try:
        cli = TradeClient()  # type: ignore
        await cli.close_position_market(symbol)  # type: ignore
        if desired in ("BUY","SELL"):
            qty = abs(amt) or DEFAULT_QTY
            await cli.open_market(symbol, desired, qty=qty, leverage=DEFAULT_LEVERAGE)  # type: ignore
        AF_LAST_FLIP[symbol] = now_ts
        await emit(symbol, "auto_flip", from_side=side_now or "FLAT", to=desired)
        logger.info("WS auto-flip %s -> %s (was %s) px=%.4f", symbol, desired, side_now, price)
    except Exception as e:
        logger.debug("WS auto_flip %s failed: %s", symbol, e)

async def _symbols_to_track() -> List[str]:
    wanted: Set[str] = set()
    try:
        if get_positions_snapshot:
            snap = await get_positions_snapshot()
            for row in (snap or []):
                sym = str(row.get("symbol") or "").upper()
                amt = float(row.get("positionAmt") or 0.0)
                if sym and abs(amt) != 0.0:
                    wanted.add(sym)
    except Exception:
        pass
    for s in AF_WATCHLIST:
        if s: wanted.add(s.upper())
    out = sorted(list(wanted))
    # כבוד להגבלות נפרדות: TRAIL_RT_MAX_SYMBOLS ו-AUTOFLIP_MAX_SYMBOLS
    mx = max(1, min(TRAIL_RT_MAX_SYMBOLS, AF_MAX_SYMBOLS))
    if len(out) > mx:
        out = out[:mx]
    return out

async def _ws_autoflip_loop():
    url = f"{BINANCE_WS_BASE}/ws/!markPrice@arr"
    backoff = 1.0
    while True:
        if not (MANAGER_ENABLE and USE_WS):
            await asyncio.sleep(2.0); continue
        try:
            import websockets  # type: ignore
            async with websockets.connect(url, ping_interval=WS_KEEPALIVE_SEC*0.8, ping_timeout=WS_KEEPALIVE_SEC) as ws:
                logger.info("WS connected: %s", url)
                backoff = 1.0
                while True:
                    raw = await asyncio.wait_for(ws.recv(), timeout=WS_KEEPALIVE_SEC*1.2)
                    now_ts = time.time()
                    try:
                        data = json.loads(raw)
                    except Exception:
                        continue

                    if isinstance(data, list):
                        track = set([s.upper() for s in (await _symbols_to_track())])
                        for it in data:
                            s = str(it.get("s","")).upper()
                            if not s or (track and s not in track):
                                continue
                            try:
                                p = float(it.get("p") or it.get("markPrice") or 0.0)
                                if p > 0:
                                    PRICE_MAP[s] = p
                                    LAST_PRICE_TS[s] = now_ts
                            except Exception:
                                pass

                        # 1) ניהול חי (SL/TP)
                        for s in track:
                            await _rt_manage(s)
                        # 2) אוטו-פליפ חכם
                        for s in track:
                            await _maybe_eval_and_flip(s)
        except Exception as e:
            logger.warning("WS loop error: %s", e)
            await asyncio.sleep(min(30.0, backoff))
            backoff = min(30.0, backoff*1.7)

async def _manager_loop():
    logger.info("manager_loop start: enable=%s interval=%ss ingest_dir=%s alerts_ingest=%s writes_orders=%s native_tpsl=%s auto_flip=%s ws=%s rt_manage=%s",
                MANAGER_ENABLE, MANAGER_INTERVAL_SEC, INGEST_DIR,
                ALERTS_INGEST_URL or "DISABLED", MANAGER_WRITES_ORDERS, NATIVE_TPSL_ENABLE,
                AUTO_FLIP_ENABLE, USE_WS, TRAIL_RT_ENABLE)
    while True:
        try:
            await _tick_once()
        except Exception as e:
            logger.error("manager_loop error: %s", e)
            try:
                POS_LIVE_ERRORS.labels("ALL", "manager_loop").inc()
            except Exception:
                pass
        await asyncio.sleep(max(3, MANAGER_INTERVAL_SEC))

@router.on_event("startup")
async def _startup():
    if MANAGER_ENABLE:
        asyncio.create_task(_manager_loop())
    global _WS_TASK
    if MANAGER_ENABLE and USE_WS and _WS_TASK is None:
        try:
            _WS_TASK = asyncio.create_task(_ws_autoflip_loop())
        except Exception as e:
            logger.error("ws_autoflip start failed: %s", e)
            try:
                POS_LIVE_ERRORS.labels("ALL", "ws_start").inc()
            except Exception:
                pass

def main() -> None:
    if not MANAGER_ENABLE:
        print("MANAGER_ENABLE=0 — exiting.")
        return
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.create_task(_manager_loop())
        if USE_WS:
            loop.create_task(_ws_autoflip_loop())
        loop.run_forever()
    except KeyboardInterrupt:
        pass


