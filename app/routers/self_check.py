# app/routers/self_check.py
import os, time, hmac, hashlib, json, uuid, asyncio
from typing import Dict, Any
from fastapi import APIRouter, Header, HTTPException
import httpx, redis
import yaml, jsonschema

router = APIRouter(tags=["internal"], include_in_schema=False)

REQUIRED_SECRETS = [
    "OPENAI_API_KEY", "BINANCE_API_KEY", "BINANCE_API_SECRET",
    "API_BEARER_TOKEN", "API_SIGNING_SECRET", "OPS_SIGN_SECRET", "REDIS_URL"
]

POLICY_PATH = os.getenv("POLICY_DSL_PATH", "policies/dynamic_policy.yaml")
SCHEMA_PATH = os.getenv("POLICY_SCHEMA_PATH", "config/policy_schema.json")
BINANCE_FAPI = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com")

def verify_sig(headers: Dict[str, str], body: bytes) -> None:
    secret = os.getenv("OPS_SIGN_SECRET", "")
    if not secret:
        raise HTTPException(status_code=500, detail="OPS_SIGN_SECRET missing")
    ts = headers.get("x-ops-ts")
    nonce = headers.get("x-ops-nonce")
    sig = headers.get("x-ops-signature")
    if not (ts and nonce and sig):
        raise HTTPException(status_code=401, detail="Missing signature headers")
    payload = (ts + "." + nonce + ".").encode("utf-8") + body
    calc = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, sig):
        raise HTTPException(status_code=401, detail="Bad signature")
    # 2 דקות חלון
    if abs(time.time() - float(ts)) > 120:
        raise HTTPException(status_code=401, detail="Signature expired")

async def ping_binance() -> Dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{BINANCE_FAPI}/fapi/v1/ping")
            ok = r.status_code == 200
            return {"ok": ok, "status_code": r.status_code, "latency_ms": r.elapsed.total_seconds()*1000}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def ping_redis() -> Dict[str, Any]:
    url = os.getenv("REDIS_URL")
    try:
        r = redis.from_url(url, socket_timeout=2.0, socket_connect_timeout=2.0)
        t0 = time.time()
        pong = r.ping()
        ms = (time.time() - t0) * 1000
        return {"ok": bool(pong), "latency_ms": ms}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def validate_policy() -> Dict[str, Any]:
    try:
        with open(POLICY_PATH, "r", encoding="utf-8") as fh:
            policy = yaml.safe_load(fh)
        with open(SCHEMA_PATH, "r", encoding="utf-8") as fh:
            schema = json.load(fh)
        jsonschema.validate(policy, schema)
        return {"ok": True}
    except jsonschema.ValidationError as ve:
        return {"ok": False, "error": f"schema: {ve.message}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def check_secrets() -> Dict[str, Any]:
    missing = [k for k in REQUIRED_SECRETS if not os.getenv(k)]
    return {"ok": len(missing) == 0, "missing": missing}

def check_ranges() -> Dict[str, Any]:
    # בדיקות לוגיות קצרות מול env דינמיים
    issues = []
    def _num(key, default):
        try:
            return float(os.getenv(key, str(default)))
        except:
            issues.append(f"{key} not numeric")
            return default
    a_min = _num("AUTO_LEV_MIN", 15)
    a_max = _num("AUTO_LEV_MAX", 25)
    if a_min > a_max:
        issues.append("AUTO_LEV_MIN > AUTO_LEV_MAX")
    d_min = _num("DYNAMIC_MAX_TRADE_BUDGET_MIN", 200)
    d_max = _num("DYNAMIC_MAX_TRADE_BUDGET_MAX", 600)
    if d_min > d_max:
        issues.append("DYNAMIC_MAX_TRADE_BUDGET_MIN > DYNAMIC_MAX_TRADE_BUDGET_MAX")
    return {"ok": not issues, "issues": issues}

async def _run_self_check() -> Dict[str, Any]:
    res = {}
    res["policy"] = validate_policy()
    res["secrets"] = check_secrets()
    res["redis"] = ping_redis()
    res["binance"] = await ping_binance()
    res["ranges"] = check_ranges()
    overall = all(x.get("ok", False) for x in res.values())
    return {"ok": overall, "checks": res, "ts": int(time.time())}

@router.get("/internal/self-check")
async def self_check():
    return await _run_self_check()

@router.post("/internal/self-check/signed")
async def self_check_signed(
    x_ops_ts: str = Header(None, convert_underscores=False),
    x_ops_nonce: str = Header(None, convert_underscores=False),
    x_ops_signature: str = Header(None, convert_underscores=False),
    body: bytes = b""
):
    # אימות חתימה
    verify_sig({"x-ops-ts": x_ops_ts, "x-ops-nonce": x_ops_nonce, "x-ops-signature": x_ops_signature}, body)
    return await _run_self_check()
