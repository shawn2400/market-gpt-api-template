# verify_api.py
import json, sys, os, re
from pathlib import Path

# 1) ניתוח openapi.yaml/json מקומי (אם אין YAML, ננסה JSON)
def load_openapi_file():
    p_yaml = Path("openapi.yaml")
    p_json = Path("openapi.json")
    if p_yaml.exists():
        import yaml
        return yaml.safe_load(p_yaml.read_text(encoding="utf-8")), "yaml"
    elif p_json.exists():
        return json.loads(p_json.read_text(encoding="utf-8")), "json"
    else:
        print("[FAIL] no openapi.yaml/json found")
        sys.exit(1)

# 2) חילוץ גרסת APP מה-main.py
def extract_app_version():
    txt = Path("main.py").read_text(encoding="utf-8")
    m = re.search(r'APP_VERSION\s*=\s*["\']([\d.]+)["\']', txt)
    return m.group(1) if m else None

# 3) בדיקות operationId מול שמות פונקציות (לפי הנהוג אצלך)
def extract_route_funcs():
    txt = Path("main.py").read_text(encoding="utf-8")
    # מפה לשיוך נתיב->שם פונקציה
    routes = {}
    for m in re.finditer(r'@app\.(get|post)\(\s*["\']([^"\']+)["\'].*?\)\s*\nasync def\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(', txt, re.S):
        method, path, fn = m.group(1).lower(), m.group(2), m.group(3)
        routes.setdefault(path, {})[method] = fn
    return routes

def main():
    spec, kind = load_openapi_file()
    app_ver = extract_app_version()
    spec_ver = spec.get("info", {}).get("version")

    ok = True

    # A) version
    if app_ver and spec_ver and app_ver != spec_ver:
        print(f"[FAIL] version mismatch: main.py={app_ver}, openapi={spec_ver}")
        ok = False
    else:
        print(f"[OK] version match: {spec_ver}")

    # B) security of open endpoints
    for path in ["/", "/scan/multi"]:
        ep = spec.get("paths", {}).get(path, {})
        for method in ("get",):
            if ep.get(method, {}).get("security", None) not in ([],):
                print(f"[FAIL] {path} should be open: security: []")
                ok = False
            else:
                print(f"[OK] {path} is open")

    # C) required paths exist
    must_paths = ["/", "/scan/multi", "/trade", "/ai-analyze", "/sltp", "/price",
                  "/executor/start", "/executor/stop", "/executor/status",
                  "/report/pnl/pdf", "/debug/binance-futures"]
    missing = [p for p in must_paths if p not in spec.get("paths", {})]
    if missing:
        print(f"[FAIL] missing paths in openapi: {missing}")
        ok = False
    else:
        print("[OK] all core paths exist")

    # D) operationId == function name (בהנחה שה-patch פעיל)
    route_funcs = extract_route_funcs()
    for p, methods in route_funcs.items():
        if p not in spec.get("paths", {}):  # אולי מ-router חיצוני
            continue
        for m, fn in methods.items():
            oid = spec["paths"][p][m].get("operationId")
            if oid != fn:
                print(f"[FAIL] {p} {m}: operationId '{oid}' != '{fn}'")
                ok = False
            else:
                print(f"[OK] {p} {m}: operationId == {fn}")

    # E) nullable legacy check
    spec_s = json.dumps(spec, ensure_ascii=False)
    if '"nullable": true' in spec_s:
        print("[FAIL] found legacy 'nullable': true — use type: [T, 'null']")
        ok = False
    else:
        print("[OK] no legacy nullable usage")

    if not ok:
        sys.exit(2)
    print("[ALL GOOD] spec and code look consistent")

if __name__ == "__main__":
    main()
