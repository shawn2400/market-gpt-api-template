# fixbot/feature_scan.py
from __future__ import annotations
import os, re, json, fnmatch, ast
from typing import List, Dict, Any

PY_EXT = (".py",)

def _walk(root: str, include_globs: List[str], exclude_globs: List[str]) -> List[str]:
    files: List[str] = []
    for d, _, fs in os.walk(root):
        rel_d = os.path.relpath(d, root)
        if any(fnmatch.fnmatch(rel_d, g) for g in exclude_globs):
            continue
        for f in fs:
            rel = os.path.join(rel_d, f) if rel_d != "." else f
            if include_globs and not any(fnmatch.fnmatch(rel, g) for g in include_globs):
                continue
            files.append(rel)
    return sorted(files) if include_globs else _walk_all(root, exclude_globs)

def _walk_all(root: str, exclude_globs: List[str]) -> List[str]:
    out=[]
    for d,_,fs in os.walk(root):
        rel_d = os.path.relpath(d, root)
        if any(fnmatch.fnmatch(rel_d, g) for g in exclude_globs):
            continue
        for f in fs:
            out.append(os.path.join(rel_d, f) if rel_d!="." else f)
    return sorted(out)

def build_repo_map(root: str, include_globs: List[str], exclude_globs: List[str]) -> Dict[str, Any]:
    files = _walk(root, include_globs, exclude_globs)
    py_files = [f for f in files if f.endswith(PY_EXT)]
    meta=[]
    for p in py_files:
        meta.append(_analyze_py(os.path.join(root,p), p))
    return {"files": files, "py_meta": meta}

def _analyze_py(abs_path: str, rel_path: str) -> Dict[str, Any]:
    res={"path": rel_path, "imports": [], "fastapi_apps": [], "routers": []}
    try:
        src=open(abs_path,"r",encoding="utf-8").read()
        t=ast.parse(src)
        for n in ast.walk(t):
            if isinstance(n, ast.Import):
                for a in n.names: res["imports"].append(a.name.split(".")[0])
            elif isinstance(n, ast.ImportFrom) and n.module:
                res["imports"].append(n.module.split(".")[0])
            elif isinstance(n, ast.Assign):
                if any(getattr(x, "id", "")=="FastAPI" for x in ast.walk(n.value)):
                    for tgt in n.targets:
                        if getattr(tgt, "id", None): res["fastapi_apps"].append(tgt.id)  # app var name
            elif isinstance(n, ast.Call):
                if getattr(getattr(n, "func", None), "attr", "") == "include_router":
                    res["routers"].append("include_router")
    except Exception:
        pass
    return res

# === ליבת ניתוח ה-logs מה-SHELL/CI ===
def analyze_shell_output(shell: str) -> Dict[str, Any]:
    issues: List[Dict[str,Any]] = []
    # דוגמאות דיאגנוסטיות נפוצות:
    if "ModuleNotFoundError" in shell:
        m = re.search(r"ModuleNotFoundError: No module named '([^']+)'", shell)
        if m:
            issues.append({"type":"missing_dependency","detail":m.group(1)})
    if "ImportError: cannot import name" in shell:
        issues.append({"type":"import_break","detail":"incompatible import (pydantic/fastapi?)"})
    if re.search(r"-1021|Timestamp .* outside", shell):
        issues.append({"type":"binance_timestamp","detail":"clock skew/recvWindow"})
    if "AttributeError" in shell and "object has no attribute" in shell:
        issues.append({"type":"attribute_error","detail":"API change or stale code"})
    if "NameError: name" in shell:
        issues.append({"type":"name_error","detail":"missing symbol/typo"})
    if "EADDRINUSE" in shell or "address already in use" in shell:
        issues.append({"type":"port_conflict","detail":"uvicorn port in use"})
    return {"issues_from_shell": issues}

def analyze_feature_area(repo_map: Dict[str,Any], feature: str, hints: List[str], shell_output: str) -> Dict[str, Any]:
    # מסנן קבצים רלוונטיים לפי hints/מילות מפתח
    candidates: List[str] = []
    keys = hints + [feature]
    keys = [k.lower() for k in keys if k.strip()]
    for f in repo_map["files"]:
        low = f.lower()
        if any(k in low for k in keys):
            candidates.append(f)
    # הרחבה: קבצים עם app/routes/trade/manage/manager
    for f in repo_map["files"]:
        low=f.lower()
        if any(k in low for k in ["trade", "manage", "manager", "routes", "utils", "executor"]) and f not in candidates:
            candidates.append(f)

    # חיבור ממצאי logs
    log_diag = analyze_shell_output(shell_output)
    return {
        "relevant_files": sorted(set(candidates)),
        "shell_diagnostics": log_diag["issues_from_shell"]
    }
