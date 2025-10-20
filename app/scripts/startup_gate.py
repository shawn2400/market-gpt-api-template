# app/scripts/startup_gate.py
# Minimal start-up gate: Redis + policy YAML schema + params/optimized/*.json
from __future__ import annotations

import os, sys, json, glob, traceback
from typing import Any, Dict, Tuple

# deps: pip install redis PyYAML jsonschema
import yaml
from jsonschema import Draft7Validator
from urllib.parse import urlparse

# שימוש בלקוח האחיד שננעל ל-URL בלבד
from utils.redis_client import make_client as make_redis_client


def _log(msg: str) -> None:
    print(f"[startup-gate] {msg}", flush=True)


def _fail(msg: str, verbose: bool) -> bool:
    _log(f"❌ {msg}")
    if verbose:
        traceback.print_exc()
    return False


def ping_redis(verbose: bool = False) -> bool:
    """PING Redis using REDIS_URL (או ALGOGPT_REDIS_URL) — ללא ssl=, לפי ה-URL בלבד."""
    url = os.getenv("REDIS_URL") or os.getenv("ALGOGPT_REDIS_URL")
    if not url:
        _log("⚠️  REDIS_URL/ALGOGPT_REDIS_URL not set — skipping Redis check")
        return True  # לא נכשל קשיח אם מבטלים Redis במכוון

    try:
        scheme = (urlparse(url).scheme or "").lower()
        if scheme not in ("redis", "rediss"):
            return _fail("REDIS_URL must start with redis:// or rediss://", verbose)

        # יצירת לקוח דרך ה-factory שנעול ל-URL
        client = make_redis_client()

        pong = client.ping()
        if pong:
            _log("✅ Redis PING OK")
            return True
        return _fail("Redis ping returned false", verbose)
    except Exception as e:
        return _fail(f"Redis connection error: {e}", verbose)


def load_yaml(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def validate_policy_schema(policy_path: str, schema_path: str, verbose: bool = False) -> bool:
    """Validate YAML policy against JSON schema + a few semantic sanity checks."""
    try:
        policy = load_yaml(policy_path)
    except FileNotFoundError:
        return _fail(f"Policy file not found: {policy_path}", verbose)
    except Exception as e:
        return _fail(f"Failed to read policy YAML: {e}", verbose)

    try:
        schema = load_json(schema_path)
    except FileNotFoundError:
        return _fail(f"Schema file not found: {schema_path}", verbose)
    except Exception as e:
        return _fail(f"Failed to read schema JSON: {e}", verbose)

    try:
        Draft7Validator(schema).validate(policy)
    except Exception as e:
        return _fail(f"Schema validation failed: {e}", verbose)

    # --- Semantic sanity checks (optional but helpful) ---
    try:
        # ladder.tp.splits should sum ~ 1.0 (±0.05)
        tp = (policy.get("ladder") or {}).get("tp") or {}
        splits = tp.get("splits")
        if splits:
            s = float(sum(splits))
            if not (0.95 <= s <= 1.05):
                return _fail(f"ladder.tp.splits sum must be ~1.0 (±0.05). got {s:.4f}", verbose)

        # trailing.callback_min_pct <= callback_max_pct
        trailing = policy.get("trailing") or {}
        cmin, cmax = trailing.get("callback_min_pct"), trailing.get("callback_max_pct")
        if cmin is not None and cmax is not None and cmin > cmax:
            return _fail(f"trailing.callback_min_pct ({cmin}) > callback_max_pct ({cmax})", verbose)

        # breakeven.offset_bps reasonable (0..50)
        breakeven = policy.get("breakeven") or {}
        off = breakeven.get("offset_bps")
        if off is not None and not (0 <= float(off) <= 50):
            return _fail(f"breakeven.offset_bps out of range (0..50): {off}", verbose)

    except Exception as e:
        return _fail(f"Semantic checks error: {e}", verbose)

    _log(f"✅ Policy schema + semantic checks OK ({policy_path})")
    return True


def verify_params_dir(params_dir: str, verbose: bool = False) -> bool:
    """Ensure at least one JSON exists and is syntactically valid."""
    try:
        pattern = os.path.join(params_dir, "*.json")
        files = sorted(glob.glob(pattern))
        if not files:
            return _fail(f"No JSON files found in {params_dir}", verbose)

        bad: list[Tuple[str, str]] = []
        for p in files:
            try:
                load_json(p)  # רק בדיקת תחביר
            except Exception as e:
                bad.append((p, str(e)))

        if bad:
            details = "; ".join([f"{p}: {err}" for p, err in bad[:5]])
            return _fail(f"Invalid JSON in params ({len(bad)} files): {details}", verbose)

        _log(f"✅ Params OK: {len(files)} file(s) under {params_dir}")
        return True
    except Exception as e:
        return _fail(f"Params check error: {e}", verbose)


def main(argv: list[str] | None = None) -> bool:
    argv = argv or sys.argv[1:]
    verbose = ("-v" in argv) or ("--verbose" in argv)
    strict = ("--strict" in argv)  # אם True, גם Redis לא מוגדר יכשיל

    ok_all = True

    # 1) Redis
    ok_redis = ping_redis(verbose=verbose)
    if strict and not ok_redis:
        ok_all = False
    elif not ok_redis:
        # Non-strict mode: רק אם REQUIRE_REDIS=1 נתייחס ככשל
        if os.getenv("REQUIRE_REDIS", "1") == "1":
            ok_all = False

    # 2) Policy schema
    policy_path = os.getenv("POLICY_DSL_PATH", "policies/dynamic_policy.yaml")
    schema_path = os.getenv("POLICY_SCHEMA_PATH", "config/policy_schema.json")
    ok_policy = validate_policy_schema(policy_path, schema_path, verbose=verbose)
    ok_all = ok_all and ok_policy

    # 3) Params dir
    params_dir = os.getenv("PARAMS_DIR", "params/optimized")
    ok_params = verify_params_dir(params_dir, verbose=verbose)
    ok_all = ok_all and ok_params

    if ok_all:
        _log("🎉 All startup checks passed")
    else:
        _log("🛑 Startup checks failed")

    return ok_all


if __name__ == "__main__":
    sys.exit(0 if main() else 23)


