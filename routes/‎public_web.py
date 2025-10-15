# routes/public_web.py
from __future__ import annotations
import os, html
from typing import Optional
from fastapi import APIRouter, Header, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse

router = APIRouter(tags=["Public Feed"])

PUBLIC_REQUIRE_BEARER = os.getenv("PUBLIC_REQUIRE_BEARER", "1").lower() in ("1","true","yes","on")
API_BEARER_TOKEN = (os.getenv("API_BEARER_TOKEN") or os.getenv("API_TOKEN") or "").strip()

try:
    from utils.rate_limit_tb import tb_allow  # type: ignore
except Exception:
    async def tb_allow(ip: str, path: str, sse_hint: bool=False):
        return True, None

def _bearer_ok(auth_header: Optional[str]) -> bool:
    if not PUBLIC_REQUIRE_BEARER:
        return True
    if not API_BEARER_TOKEN:
        return False
    if not (auth_header and auth_header.startswith("Bearer ")):
        return False
    return auth_header.split(" ", 1)[1].strip() == API_BEARER_TOKEN

def _csp_headers() -> dict:
    return {
        "Content-Security-Policy": "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; script-src 'self'; frame-ancestors 'none'",
        "X-Frame-Options": "DENY",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
    }

@router.get("/topk")  # legacy redirect
async def topk_legacy_redirect():
    return RedirectResponse("/scan/public-topk", status_code=307)

@router.get("/scan/public-topk/web")
async def topk_web(request: Request, authorization: Optional[str] = Header(None, alias="Authorization")):
    if not _bearer_ok(authorization):
        return PlainTextResponse("Unauthorized", status_code=401)
    ip = (request.client.host if request.client else "0.0.0.0")
    allowed, ra = await tb_allow(ip, request.url.path, sse_hint=False)
    if not allowed:
        resp = PlainTextResponse("rate_limited", status_code=429)
        if ra:
            resp.headers["Retry-After"] = str(ra)
        return resp

    # מינימל־דף: מושך SSE מ-/scan/public-stream ומעדכן טבלה
    html_doc = f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<title>TopK — Live</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body{{font-family:system-ui,Segoe UI,Roboto,Arial,sans-serif;margin:0;padding:16px;background:#0b0d10;color:#e2e8f0}}
table{{width:100%;border-collapse:collapse;margin-top:12px}}
th,td{{padding:8px;border-bottom:1px solid #1f2937;font-size:14px}}
th{{text-align:left;color:#93c5fd}}
.badge{{display:inline-block;padding:2px 6px;border-radius:6px;background:#1f2937}}
.up{{color:#10b981}} .down{{color:#ef4444}}
small{{color:#93a3b8}}
</style>
</head><body>
<h2>TopK <small>live</small></h2>
<table id="t"><thead><tr>
<th>Symbol</th><th>Side</th><th>Score</th><th>Why</th><th>TF</th><th>TS</th>
</tr></thead><tbody></tbody></table>
<script>
const tbody = document.querySelector("#t tbody");
function fmtTs(ts){{try{{return new Date(ts*1000).toISOString().replace('T',' ').slice(0,19)}}catch{{return ts}}}}
function render(items){{tbody.innerHTML = ""; (items||[]).forEach(it=>{{
  const tr = document.createElement("tr");
  const side = (String(it.side||"").toUpperCase()==="BUY") ? "<span class='badge up'>BUY</span>" : "<span class='badge down'>SELL</span>";
  tr.innerHTML = `
    <td>${{it.symbol||""}}</td>
    <td>${{side}}</td>
    <td>${{(it.score||0).toFixed?it.score.toFixed(2):it.score}}</td>
    <td>${{(it.reason||"")}}</td>
    <td>${{it.timeframe||""}}</td>
    <td><small>${{fmtTs(it.ts||0)}}</small></td>
  `;
  tbody.appendChild(tr);
}})}}
function oneShot(){{
  fetch("/scan/public-topk", {{headers: {{}}}})
   .then(r=>r.json()).then(j=>render(j.items||[])).catch(()=>{});
}}
oneShot();
const ev = new EventSource("/scan/public-stream");
ev.addEventListener("topk", (e)=>{{try{{const d = JSON.parse(e.data); render(d.items||[])}}catch{{}}}});
</script>
</body></html>"""
    return HTMLResponse(html_doc, headers=_csp_headers())

@router.get("/scan/public-now/web")
async def now_web(request: Request, authorization: Optional[str] = Header(None, alias="Authorization")):
    if not _bearer_ok(authorization):
        return PlainTextResponse("Unauthorized", status_code=401)
    ip = (request.client.host if request.client else "0.0.0.0")
    allowed, ra = await tb_allow(ip, request.url.path, sse_hint=False)
    if not allowed:
        resp = PlainTextResponse("rate_limited", status_code=429)
        if ra:
            resp.headers["Retry-After"] = str(ra)
        return resp

    html_doc = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><title>Now — Live</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body{font-family:system-ui,Segoe UI,Roboto,Arial,sans-serif;margin:0;padding:16px;background:#0b0d10;color:#e2e8f0}
table{width:100%;border-collapse:collapse;margin-top:12px}
th,td{padding:8px;border-bottom:1px solid #1f2937;font-size:14px}
th{text-align:left;color:#93c5fd}
.badge{display:inline-block;padding:2px 6px;border-radius:6px;background:#1f2937}
.up{color:#10b981} .down{color:#ef4444}
small{color:#93a3b8}
</style>
</head><body>
<h2>Now <small>live</small></h2>
<table id="t"><thead><tr>
<th>Symbol</th><th>Side</th><th>Price</th><th>Why</th><th>TF</th><th>TS</th>
</tr></thead><tbody></tbody></table>
<script>
const tbody = document.querySelector("#t tbody");
function fmtTs(ts){try{return new Date(ts*1000).toISOString().replace('T',' ').slice(0,19)}catch{return ts}}
function render(items){tbody.innerHTML = ""; (items||[]).forEach(it=>{
  const tr = document.createElement("tr");
  const side = (String(it.side||"").toUpperCase()==="BUY") ? "<span class='badge up'>BUY</span>" : "<span class='badge down'>SELL</span>";
  tr.innerHTML = `
    <td>${it.symbol||""}</td>
    <td>${side}</td>
    <td>${(it.price||0)}</td>
    <td>${(it.reason||"")}</td>
    <td>${it.timeframe||""}</td>
    <td><small>${fmtTs(it.ts||0)}</small></td>
  `;
  tbody.appendChild(tr);
})}
function oneShot(){
  fetch("/scan/public-now", {headers: {}}).then(r=>r.json()).then(j=>render(j.items||[])).catch(()=>{});
}
oneShot();
const ev = new EventSource("/scan/public-stream");
ev.addEventListener("now", (e)=>{try{const d = JSON.parse(e.data); render(d.items||[])}catch{}});
</script>
</body></html>"""
    return HTMLResponse(html_doc, headers=_csp_headers())
