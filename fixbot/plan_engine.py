# fixbot/plan_engine.py
from __future__ import annotations
import os, json, uuid, subprocess, shutil
from typing import Dict, Any, List

_PLANS: Dict[str, Dict[str,Any]] = {}

def build_fix_plan(repo_map: Dict[str,Any], feature_ctx: Dict[str,Any]) -> Dict[str,Any]:
    plan_id = uuid.uuid4().hex[:10]
    issues = []
    changes = []

    # הפקת תכנית ראשונית לפי דיאגנוסטיקה
    for iss in feature_ctx["shell_diagnostics"]:
        if iss["type"] == "missing_dependency":
            pkg = iss["detail"]
            issues.append({"type":"missing_dependency", "pkg":pkg})
            changes.append({"action":"ensure_dep", "file":"pyproject.toml", "description":f"add `{pkg}` to dependencies if missing"})
        if iss["type"] == "binance_timestamp":
            issues.append(iss)
            changes.append({"action":"ensure_timesync","file":"utils/binance_client.py","description":"sync server time + recvWindow=45000"})
        if iss["type"] == "import_break":
            issues.append(iss)
            changes.append({"action":"audit_imports","file":"(multiple)","description":"update pydantic/fastapi imports for v2"})
        if iss["type"] == "attribute_error":
            issues.append(iss)
            changes.append({"action":"api_change_check","file":"(multiple)","description":"fix renamed attributes + fallback shims"})
        if iss["type"] == "name_error":
            issues.append(iss)
            changes.append({"action":"define_missing_symbol","file":"(context)","description":"add missing function/const or import"})
        if iss["type"] == "port_conflict":
            issues.append(iss)
            changes.append({"action":"change_port","file":"Procfile/Docker","description":"use env PORT or find free port"})

    # קבצים מושפעים
    affected = feature_ctx["relevant_files"]

    plan = {
        "plan_id": plan_id,
        "summary": "Automatic plan for feature area based on repository map + shell logs.",
        "affected_files": affected,
        "issues": issues,
        "proposed_changes": changes
    }
    _PLANS[plan_id] = plan
    return plan

def apply_plan_changes(plan_id: str, repo_url: str, branch: str, bot_name: str, bot_email: str) -> Dict[str,Any]:
    if plan_id not in _PLANS:
        raise RuntimeError("unknown plan_id")
    plan = _PLANS[plan_id]
    tmp = None
    try:
        tmp = _git_clone(repo_url, bot_name, bot_email)
        _git_checkout(tmp, branch)
        # יישום שינויים שמרניים/אידמפוטנטיים:
        _apply_idempotent_fixes(tmp, plan["proposed_changes"])
        _git_push(tmp, branch)
        pr_url = _open_pr(repo_url, branch, f"Fix: {plan['summary']}", json.dumps(plan, ensure_ascii=False))
        return {"ok": True, "branch": branch, "pr_url": pr_url}
    finally:
        if tmp: shutil.rmtree(tmp, ignore_errors=True)

# ——— helpers (מינימליים; השאר כמו בקוד הקודם שלך/שלי) ———
def _run(cmd: str, cwd: str=None):
    p = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(p.stdout + "\n" + p.stderr)
    return p.stdout

def _git_clone(repo_url: str, bot_name: str, bot_email: str) -> str:
    import tempfile
    tmp = tempfile.mkdtemp(prefix="fixplan_")
    _run(f"git clone --filter=blob:none --depth=1 {repo_url} .", cwd=tmp)
    _run(f"git config user.name '{bot_name}'", cwd=tmp)
    _run(f"git config user.email '{bot_email}'", cwd=tmp)
    return tmp

def _git_checkout(tmp: str, branch: str):
    _run(f"git checkout -B {branch}", cwd=tmp)

def _git_push(tmp: str, branch: str):
    _run("git add -A", cwd=tmp)
    _run('git commit -m "fixbot: apply plan"', cwd=tmp)
    _run(f"git push -f origin {branch}", cwd=tmp)

def _open_pr(repo_url: str, branch: str, title: str, body: str) -> str:
    # repo_url חייב להיות בצורה: https://x-access-token:<TOKEN>@github.com/<owner>/<repo>.git
    import httpx, re
    m = re.search(r"github\.com/(.+)\.git$", repo_url)
    repo = m.group(1) if m else ""
    headers = {"Accept":"application/vnd.github+json"}
    # GH_TOKEN כבר כלול ב-URL; אם תרצה – העבר גם Header Authorization
    with httpx.Client(timeout=20.0) as cli:
        r = cli.post(f"https://api.github.com/repos/{repo}/pulls",
                     json={"title":title,"head":branch,"base":"main","body":body})
        if r.status_code not in (200,201):
            raise RuntimeError(f"open PR failed: {r.status_code} {r.text}")
        return r.json().get("html_url","")

def _apply_idempotent_fixes(tmp: str, changes: List[Dict[str,Any]]):
    import os
    pyproject = os.path.join(tmp, "pyproject.toml")
    for ch in changes:
        if ch["action"] == "ensure_dep" and os.path.exists(pyproject):
            _ensure_dep(pyproject, ch["description"])
        elif ch["action"] == "ensure_timesync":
            # מוסיף בלוק timesync אם חסר (דוגמה; תתאים ל-utils/binance_client אצלך)
            _inject_timesync(tmp)
        # הרחב כאן חוקים לפי הצורך (pydantic v2, imports, __init__.py וכו')

def _ensure_dep(pyproject: str, desc: str):
    import io
    txt = open(pyproject,"r",encoding="utf-8").read()
    if "dependencies" not in txt:
        txt = txt.replace("[project]", "[project]\ndependencies = []\n")
    if "fastapi" in desc and "fastapi" not in txt:
        txt = txt.replace("dependencies = [", 'dependencies = ["fastapi>=0.111","uvicorn>=0.30", ')
    open(pyproject,"w",encoding="utf-8").write(txt)

def _inject_timesync(tmp: str):
    # דוגמה: יוצר קובץ עזר אם חסר
    util = os.path.join(tmp, "utils", "time_sync.py")
    os.makedirs(os.path.dirname(util), exist_ok=True)
    if not os.path.exists(util):
        open(util,"w",encoding="utf-8").write(
            "import httpx, time\n"
            "def server_offset_ms(base='https://fapi.binance.com'):\n"
            "    with httpx.Client(timeout=5.0) as c:\n"
            "        t = c.get(base+'/fapi/v1/time').json()['serverTime']\n"
            "    return int(t - time.time()*1000)\n"
        )
