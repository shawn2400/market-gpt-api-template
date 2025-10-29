# fixbot/planner.py
from __future__ import annotations
import os, ast, json, re
from typing import Dict, List, Any, Tuple

PY_EXT = (".py",)

def walk_repo(root: str) -> List[str]:
    out=[]
    for d,_,files in os.walk(root):
        if d.startswith((".git", ".venv", "node_modules", "dist", "build")): continue
        for f in files:
            if f.endswith(PY_EXT) or f in ("pyproject.toml","requirements.txt","Dockerfile","render.yaml",".env",".env.example"):
                out.append(os.path.join(d,f))
    return sorted(out)

def analyze_python(path: str) -> Dict[str, Any]:
    res={"path":path,"imports":[], "fastapi_apps":[], "routers":[]}
    try:
        src=open(path,"r",encoding="utf-8").read()
        t=ast.parse(src)
        for n in ast.walk(t):
            if isinstance(n, ast.Import):
                for a in n.names: res["imports"].append(a.name.split(".")[0])
            elif isinstance(n, ast.ImportFrom):
                if n.module: res["imports"].append(n.module.split(".")[0])
            elif isinstance(n, ast.Assign):
                # app = FastAPI(...)
                if any(isinstance(t, ast.Name) and t.id=="FastAPI" for t in ast.walk(n.value)):
                    for tgt in n.targets:
                        if isinstance(tgt, ast.Name): res["fastapi_apps"].append(tgt.id)
            elif isinstance(n, ast.Call):
                # app.include_router(xxx)
                if isinstance(n.func, ast.Attribute) and n.func.attr=="include_router":
                    res["routers"].append(ast.unparse(n.args[0]) if hasattr(ast, "unparse") else "router")
    except Exception:
        pass
    return res

def build_repo_map(root: str) -> Dict[str, Any]:
    files = walk_repo(root)
    py = [p for p in files if p.endswith(".py")]
    meta = []
    for p in py:
        meta.append(analyze_python(p))
    return {"files": files, "py_meta": meta}

def detect_issues(repo_map: Dict[str, Any]) -> Dict[str, Any]:
    # דוגמאות דיאגנוסטיקה נפוצות: חסרי __init__, כפילות ראוטים, imports יתומים
    files=set(repo_map["files"])
    issues={"missing_init":[],"likely_apps":[]}
    # __init__.py בתיקיות קוד
    for f in files:
        d=os.path.dirname(f)
        if f.endswith(".py") and "/tests" not in f:
            while d and d not in (".","/"):
                init=os.path.join(d,"__init__.py")
                if ("app" in d or "utils"
