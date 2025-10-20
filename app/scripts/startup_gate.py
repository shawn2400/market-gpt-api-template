import os, time, sys, json, asyncio, httpx, redis, yaml, jsonschema

POLICY_PATH = os.getenv("POLICY_DSL_PATH", "policies/dynamic_policy.yaml")
SCHEMA_PATH = os.getenv("POLICY_SCHEMA_PATH", "config/policy_schema.json")
REDIS_URL   = os.getenv("REDIS_URL")
BINANCE_FAPI = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com")

def _print(status, msg, meta=None):
    print(json.dumps({"status": status, "msg": msg, "meta": meta or {}}, ensure_ascii=False))

def check_policy():
    try:
        with open(POLICY_PATH, "r", encoding="utf-8") as f:
            policy = yaml.safe_load(f)
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            schema = json.load(f)
        jsonschema.validate(policy, schema)
        _print("ok", "policy schema validated")
        return True
    except Exception as e:
        _print("fail", "policy validation error", {"error": str(e)})
        return False

def check_redis():
    try:
        r = redis.from_url(REDIS_URL, socket_timeout=2.0, socket_connect_timeout=2.0)
        t0 = time.time()
        pong = r.ping()
        _print("ok", "redis ping", {"lat_ms": round((time.time()-t0)*1000,2)})
        return True
    except Exception as e:
        _print("fail", "redis error", {"error": str(e)})
        return False

async def check_binance():
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{BINANCE_FAPI}/fapi/v1/ping")
            if r.status_code == 200:
                _print("ok", "binance ping", {"code": r.status_code})
                return True
            _print("fail", "binance bad status", {"code": r.status_code})
            return False
    except Exception as e:
        _print("fail", "binance error", {"error": str(e)})
        return False

def check_secrets():
    required = [
        "OPENAI_API_KEY","BINANCE_API_KEY","BINANCE_API_SECRET",
        "API_BEARER_TOKEN","API_SIGNING_SECRET","OPS_SIGN_SECRET","REDIS_URL"
    ]
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        _print("fail", "missing secrets", {"missing": missing})
        return False
    _print("ok", "secrets present")
    return True

def check_ranges():
    ok = True
    def num(k, d):
        try:
            return float(os.getenv(k, str(d)))
        except:
            return d
    a_min, a_max = num("AUTO_LEV_MIN",15), num("AUTO_LEV_MAX",25)
    if a_min > a_max:
        _print("fail", "AUTO_LEV_MIN>AUTO_LEV_MAX", {"min":a_min,"max":a_max}); ok=False
    d_min, d_max = num("DYNAMIC_MAX_TRADE_BUDGET_MIN",200), num("DYNAMIC_MAX_TRADE_BUDGET_MAX",600)
    if d_min > d_max:
        _print("fail", "DYNAMIC_MAX_TRADE_BUDGET_MIN>DYNAMIC_MAX_TRADE_BUDGET_MAX", {"min":d_min,"max":d_max}); ok=False
    if ok: _print("ok","ranges sane")
    return ok

async def main():
    if os.getenv("ENABLE_STARTUP_SELF_CHECK","1") != "1":
        _print("skip","startup self-check disabled")
        sys.exit(0)
    results = [
        check_policy(),
        check_secrets(),
        check_redis(),
        await check_binance(),
        check_ranges()
    ]
    if all(results):
        _print("ok","startup gate passed")
        sys.exit(0)
    _print("fail","startup gate failed")
    sys.exit(23)

if __name__ == "__main__":
    asyncio.run(main())
