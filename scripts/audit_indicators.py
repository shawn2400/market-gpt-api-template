import os, re, json

ROOT = "."
NAMES = [
    r"rsi", r"stoch", r"macd", r"ema(?:\d+)?", r"sma(?:\d+)?", r"wma", r"hull",
    r"atr", r"adx", r"dmi", r"supertrend", r"vwap",
    r"boll(inger)?(_?bands)?", r"keltner", r"donchian", r"psar", r"ichimoku",
    r"mfi", r"obv", r"cmf", r"cci", r"roc", r"adx_di", r"chop", r"vol(_)?spike",
    r"bb_width", r"atr_band", r"rsi_div", r"adx_slope"
]
NAME_RE = re.compile(r"^(?:" + "|".join(NAMES) + r")$", re.I)
DEF_FUN_RE = re.compile(r"^\s*def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", re.M)
DEF_CLASS_RE = re.compile(r"^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)\s*[:\(]", re.M)
ASSIGN_ALIAS_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:partial|functools\.partial|lambda|\w+\()", re.M)
CALL_RE_TMPL = r"(?<![A-Za-z0-9_]){name}\s*\("
IMPORT_RE_TMPL = r"(?i)from\s+[\w\.]+\s+import\s+.*\b{name}\b|import\s+.*\b{name}\b"

def read_text(p):
    try:
        with open(p, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return ""

py_files = []
for dp, _, files in os.walk(ROOT):
    if any(s in dp for s in [".git", ".venv", "venv", "node_modules", "dist", "build", "__pycache__", ".mypy_cache"]):
        continue
    for fn in files:
        if fn.endswith(".py"):
            py_files.append(os.path.join(dp, fn))

definitions, usages = {}, {}
file_defs, file_uses = {}, {}

for path in py_files:
    text = read_text(path)
    defs = set()
    for m in DEF_FUN_RE.finditer(text):
        n = m.group(1)
        if NAME_RE.match(n):
            n = n.lower()
            defs.add(n)
            definitions.setdefault(n, {"files": set(), "kind": "function"})["files"].add(path)
    for m in DEF_CLASS_RE.finditer(text):
        n = m.group(1)
        if NAME_RE.match(n):
            n = n.lower()
            defs.add(n)
            definitions.setdefault(n, {"files": set(), "kind": "class"})["files"].add(path)
    for m in ASSIGN_ALIAS_RE.finditer(text):
        n = m.group(1)
        if NAME_RE.match(n):
            n = n.lower()
            defs.add(n)
            definitions.setdefault(n, {"files": set(), "kind": "alias"})["files"].add(path)
    if defs:
        file_defs[path] = sorted(defs)

known_names = set(definitions.keys())
candidate_names = set(known_names)
for pat in NAMES:
    base = pat.strip("^$").split("(")[0].replace("(?:","").replace(")","").replace("?","")
    base = re.sub(r"[^A-Za-z0-9_]", "", base)
    if base:
        candidate_names.add(base.lower())
candidate_names = sorted(candidate_names)

for path in py_files:
    text = read_text(path)
    used_here = set()
    for name in candidate_names:
        call_re = re.compile(CALL_RE_TMPL.format(name=re.escape(name)))
        imp_re  = re.compile(IMPORT_RE_TMPL.format(name=re.escape(name)))
        calls = len(call_re.findall(text))
        imps  = len(imp_re.findall(text))
        if calls or imps:
            usages.setdefault(name, {"files": set(), "calls": 0, "imports": 0})
            usages[name]["files"].add(path)
            usages[name]["calls"] += calls
            usages[name]["imports"] += imps
            used_here.add(name)
    if used_here:
        file_uses[path] = sorted(used_here)

connected, not_connected = {}, {}
all_names = sorted(set(list(definitions.keys()) + list(usages.keys())))
for n in all_names:
    used = n in usages and (usages[n]["calls"] > 0 or usages[n]["imports"] > 0)
    if used:
        connected[n] = {
            "defined": n in definitions,
            "kind": definitions.get(n, {}).get("kind", "external"),
            "def_files": sorted(definitions.get(n, {}).get("files", [])),
            "use_files": sorted(usages[n]["files"]),
            "calls": usages[n]["calls"],
            "imports": usages[n]["imports"],
        }
    else:
        not_connected[n] = {
            "defined": n in definitions,
            "kind": definitions.get(n, {}).get("kind", "external"),
            "def_files": sorted(definitions.get(n, {}).get("files", [])),
        }

summary = {
    "total_py_files": len(py_files),
    "indicators_total_candidates": len(all_names),
    "indicators_defined": len(definitions),
    "indicators_connected": len(connected),
    "indicators_not_connected": len(not_connected),
    "connected_names": sorted(connected.keys()),
    "not_connected_names": sorted(not_connected.keys()),
    "by_file": {
        "definitions": {k: v for k, v in sorted(file_defs.items(), key=lambda x: (-len(x[1]), x[0]))},
        "usages": {k: v for k, v in sorted(file_uses.items(), key=lambda x: (-len(x[1]), x[0]))}
    }
}
print(json.dumps(summary, ensure_ascii=False, indent=2))
