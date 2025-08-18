# routes/dashboard.py
from __future__ import annotations
from fastapi import APIRouter
from fastapi.responses import HTMLResponse, Response

router = APIRouter(tags=["Dashboard"])

_HTML = """
<!doctype html>
<html lang="he" dir="rtl">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>AlgoGPT Dashboard</title>
  <style>
    body { font-family: system-ui, Arial, sans-serif; margin: 24px; }
    header { display:flex; align-items:center; gap:10px; margin-bottom: 20px; }
    h1 { margin:0; font-size: 1.6rem; }
    .card { border:1px solid #eee; border-radius:12px; padding:16px; margin:12px 0; }
    .row { display:flex; gap:12px; flex-wrap:wrap; align-items:center; }
    button { padding:8px 12px; border-radius:8px; border:1px solid #ddd; cursor:pointer; }
    code, pre { background:#f7f7f7; padding:4px 6px; border-radius:6px; }
    .ok { color:#0a7b18; font-weight:600; }
    .err { color:#b30000; font-weight:600; }
    table { width:100%; border-collapse: collapse; }
    th, td { padding:6px 8px; border-bottom:1px solid #eee; text-align:right; }
    input[type=text] { padding:8px; border:1px solid #ddd; border-radius:8px; min-width: 180px; }
  </style>
</head>
<body>
  <header><h1>📊 AlgoGPT Dashboard</h1></header>
  <div class="card">
    <h3>סטטוס שרת</h3>
    <div class="row">
      <button onclick="pingRoot()">בדיקת /</button>
      <button onclick="pingMetrics()">בדיקת /metrics</button>
      <button onclick="pingAI()">בדיקת /ai/health</button>
    </div>
    <pre id="rootOut"></pre>
    <pre id="metricsOut"></pre>
    <pre id="aiOut"></pre>
  </div>
  <script>
    async function pingRoot(){const o=document.getElementById('rootOut');o.textContent='טוען...';try{const r=await fetch('/',{cache:'no-store'});o.textContent=JSON.stringify(await r.json(),null,2)}catch(e){o.textContent='שגיאה: '+e}}
    async function pingMetrics(){const o=document.getElementById('metricsOut');o.textContent='טוען...';try{const r=await fetch('/metrics',{cache:'no-store'});o.textContent=JSON.stringify(await r.json(),null,2)}catch(e){o.textContent='שגיאה: '+e}}
    async function pingAI(){const o=document.getElementById('aiOut');o.textContent='טוען...';try{const r=await fetch('/ai/health',{cache:'no-store'});o.textContent=JSON.stringify(await r.json(),null,2)}catch(e){o.textContent='שגיאה: '+e}}
  </script>
</body>
</html>
"""

# GET בלבד נכנס ל־OpenAPI (operationId חדש); HEAD נרשם בלי סכימה כדי למנוע כפילות.
@router.get("/dashboard", response_class=HTMLResponse, operation_id="getDashboardHtml_v2")
async def dashboard_ui():
    return HTMLResponse(content=_HTML, media_type="text/html")

@router.head("/dashboard", include_in_schema=False)
async def dashboard_head():
    return Response(status_code=200)








