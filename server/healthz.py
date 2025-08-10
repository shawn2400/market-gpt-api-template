# server/healthz.py
from __future__ import annotations
import os
import time
import logging
from typing import Any, Dict, Tuple, Optional, List

import requests

# --- imports מהמיזם שלך ---
from utils.binance_client import get_client, ping_and_info, futures_exchange_info_safe
from utils import ws_fallback

# === תצורה (ניתנת לכיול ב-ENV) ===
MAX_TIME_OFFSET_OK_MS = int(os.getenv("HEALTH_MAX_TIME_OFFSET_MS", "2000"))   # 2s
MAX_WS_STALENESS_SEC  = int(os.getenv("HEALTH_MAX_WS_STALENESS_SEC", "15"))  # > PRICE_MAX_AGE_SEC
EXINFO_MIN_SYMBOLS    = int(os.getenv("READY_EXINFO_MIN_SYMBOLS", "10"))     # מינימום סימבולים כדי להחשיב exchangeInfo תקין
OUTBOUND_IP_ENDPOINTS = [
    "https://checkip.amazonaws.com",
    "https://api.ipify.org",
    "https://ifconfig.me/ip",
]

# ---------- Utilities ----------
def _get_outbound_ip() -> Optional[str]:
    s = requests.Session()
    s.trust_env = False
    for ep in OUTBOUND_IP_ENDPOINTS:
        try:
            r = s.get(ep, timeout=2.5)
            if r.status_code == 200:
                text = r.text.strip()
                if text:
                    return text
        except Exception:
            continue
    return None

def _check_allowlist(ip: Optional[str]) -> Tuple[bool, List[str]]:
    allowed_env = os.getenv("BINANCE_ALLOWED_EGRESS_IPS", "") or ""
    allowlist = [x.strip() for x in allowed_env.split(",") if x.strip()]
    if not allowlist or not ip:
        return True, allowlist  # אין למה להשוות → לא מפילים סטטוס
    return (ip in allowlist), allowlist

def _ws_status() -> Dict[str, Any]:
    mgr = getattr(ws_fallback, "binance_ws_manager", None)
    if mgr is None:
        return {"started": False, "connected": False, "symbols": 0, "stale_count": None}

    symbols = getattr(mgr, "symbols", []) or []
    connected = bool(getattr(mgr, "connected", False))
    ts_map = getattr(mgr, "ts", {}) or {}
    now = time.time()

    stale_count = 0
    for _, t in ts_map.items():
        if (now - float(t)) > MAX_WS_STALENESS_SEC:
            stale_count += 1

    return {
        "started": True,
        "connected": connected,
        "symbols": len(symbols),
        "stale_count": stale_count,
    }

def _binance_time_offset_ms() -> Optional[int]:
    try:
        c = get_client()
        return int(getattr(c, "timestamp_offset", 0))
    except Exception:
        return None

def _binance_ping_ok() -> bool:
    try:
        return bool(ping_and_info())
    except Exception as e:
        logging.warning(f"[healthz] ping_and_info error: {e}")
        return False

def _exchange_info_ok() -> Tuple[bool, Optional[int]]:
    """
    בדיקה מהירה שהשרת מסוגל למשוך exchangeInfo ושיש בו מספיק סמלים.
    """
    try:
        data = futures_exchange_info_safe()
        if not isinstance(data, dict):
            return False, None
        syms = data.get("symbols") or []
        return (len(syms) >= EXINFO_MIN_SYMBOLS), len(syms)
    except Exception as e:
        logging.warning(f"[readyz] exchangeInfo check error: {e}")
        return False, None

# ---------- Payload builders ----------
def build_health_payload() -> Tuple[int, Dict[str, Any]]:
    binance_ok = _binance_ping_ok()
    offset = _binance_time_offset_ms()
    time_ok = (offset is not None) and (abs(int(offset)) <= MAX_TIME_OFFSET_OK_MS)
    ws = _ws_status()
    ws_ok = ws["started"] and ws["connected"] and (ws["stale_count"] == 0)
    ip = _get_outbound_ip()
    allow_ok, allowlist = _check_allowlist(ip)

    criticals = []
    if not binance_ok: criticals.append("binance_ping")
    if not time_ok:    criticals.append("time_offset")
    if not allow_ok:   criticals.append("egress_ip_allowlist")

    warn_only = []
    if not ws_ok:      warn_only.append("ws_status")

    status_code = 200 if not criticals else 503
    payload = {
        "status": "ok" if status_code == 200 else "degraded",
        "checks": {
            "binance_ping_ok": binance_ok,
            "time_offset_ms": offset,
            "time_ok": time_ok,
            "ws": ws,
            "outbound_ip": ip,
            "allowlist_ok": allow_ok,
            "allowlist": allowlist,
        },
        "warnings": warn_only,
        "criticals": criticals,
        "meta": {
            "max_time_offset_ok_ms": MAX_TIME_OFFSET_OK_MS,
            "max_ws_staleness_sec": MAX_WS_STALENESS_SEC,
            "ts": int(time.time()),
        },
    }
    return status_code, payload

def build_ready_payload() -> Tuple[int, Dict[str, Any]]:
    """
    מחמיר יותר: דורש גם WS תקין וגם exchangeInfo תקין.
    """
    binance_ok = _binance_ping_ok()
    offset = _binance_time_offset_ms()
    time_ok = (offset is not None) and (abs(int(offset)) <= MAX_TIME_OFFSET_OK_MS)
    ws = _ws_status()
    ws_ok = ws["started"] and ws["connected"] and (ws["stale_count"] == 0)
    ex_ok, ex_count = _exchange_info_ok()
    ip = _get_outbound_ip()
    allow_ok, allowlist = _check_allowlist(ip)

    criticals = []
    if not binance_ok: criticals.append("binance_ping")
    if not time_ok:    criticals.append("time_offset")
    if not allow_ok:   criticals.append("egress_ip_allowlist")
    if not ws_ok:      criticals.append("ws_status")
    if not ex_ok:      criticals.append("exchange_info")

    status_code = 200 if not criticals else 503
    payload = {
        "status": "ready" if status_code == 200 else "not_ready",
        "checks": {
            "binance_ping_ok": binance_ok,
            "time_offset_ms": offset,
            "time_ok": time_ok,
            "ws": ws,
            "exchange_info_ok": ex_ok,
            "exchange_info_symbols": ex_count,
            "outbound_ip": ip,
            "allowlist_ok": allow_ok,
            "allowlist": allowlist,
        },
        "criticals": criticals,
        "meta": {
            "exinfo_min_symbols": EXINFO_MIN_SYMBOLS,
            "ts": int(time.time()),
        },
    }
    return status_code, payload

# ---------- Web frameworks integration ----------
def _json_dumps(payload: Dict[str, Any]) -> str:
    try:
        import orjson
        return orjson.dumps(payload).decode("utf-8")
    except Exception:
        import json
        return json.dumps(payload, separators=(",", ":"))

# FastAPI
def register_fastapi(app) -> None:
    from fastapi import Response

    @app.get("/livez")
    def livez():
        # תמיד חי אם התהליך רץ
        payload = {"status": "alive", "ts": int(time.time())}
        return Response(content=_json_dumps(payload), media_type="application/json", status_code=200)

    @app.get("/healthz")
    def healthz():
        code, payload = build_health_payload()
        return Response(content=_json_dumps(payload), media_type="application/json", status_code=code)

    @app.get("/readyz")
    def readyz():
        code, payload = build_ready_payload()
        return Response(content=_json_dumps(payload), media_type="application/json", status_code=code)

# Flask
def register_flask(app) -> None:
    from flask import Response

    @app.route("/livez", methods=["GET"])
    def livez():
        payload = {"status": "alive", "ts": int(time.time())}
        return Response(_json_dumps(payload), mimetype="application/json", status=200)

    @app.route("/healthz", methods=["GET"])
    def healthz():
        code, payload = build_health_payload()
        return Response(_json_dumps(payload), mimetype="application/json", status=code)

    @app.route("/readyz", methods=["GET"])
    def readyz():
        code, payload = build_ready_payload()
        return Response(_json_dumps(payload), mimetype="application/json", status=code)
