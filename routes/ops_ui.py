# routes/ops_ui.py
from __future__ import annotations
from fastapi import APIRouter, Body
from fastapi.responses import HTMLResponse, JSONResponse
import os
import json
import httpx

router = APIRouter(tags=["ops-ui"])

API_BASE = (os.getenv("PUBLIC_HOST", "") or "").rstrip("/")
API_TOKEN = (
    os.getenv("API_KEY")
    or os.getenv("API_BEARER_TOKEN")
    or os.getenv("API_TOKEN")
    or os.getenv("PRIMARY_API_TOKEN")
    or ""
)

HTML_PAGE = """<!doctype html>
<meta charset="utf-8">
<title>Ops Ticket UI</title>
<style>
  :root{color-scheme:light dark}
  body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;max-width:920px;margin:32px auto;padding:0 16px;line-height:1.45}
  h1{font-size:22px;margin:0 0 16px}
  fieldset{border:1px solid #ddd;padding:16px;border-radius:12px;margin:0 0 16px;background:#fafafa}
  label{display:block;margin:8px 0 6px;font-weight:600}
  input,select{width:100%;padding:9px 11px;border:1px solid #c9c9c9;border-radius:10px;font:inherit;background:#fff}
  .row{display:grid;grid-template-columns:1fr 1fr;gap:12px}
  .btns{display:flex;gap:10px;flex-wrap:wrap;margin-top:14px}
  button{padding:10px 14px;border:0;border-radius:12px;background:#222;color:#fff;cursor:pointer}
  button.variant{background:#0a7}
  button.warn{background:#08c}
  button.alt{background:#666}
  .out{white-space:pre-wrap;background:#f6f7f9;border:1px solid #e6e6e6;border-radius:10px;padding:12px;margin-top:14px;font-size:13px}
  small.hint{color:#666}
  .kvs{display:grid;grid-template-columns:160px 1fr;gap:8px;margin:10px 0 0}
  .kvs div{font-size:12px;color:#555}
</style>
<body>
  <h1>Ops • Create Ticket</h1>

  <fieldset>
    <legend>Order params</legend>
    <div class="row">
      <div>
        <label>Symbol</label>
        <input id="symbol" placeholder="e.g. BTCUSDT" value="BTCUSDT">
      </div>
      <div>
        <label>Side</label>
        <select id="side">
          <option value="BUY">BUY</option>
          <option value="SELL">SELL</option>
        </select>
      </div>
    </div>

    <div class="row">
      <div>
        <label>Qty</label>
        <input id="qty" type="number" step="0.0001" placeholder="e.g. 0.01">
      </div>
      <div>
        <label>Leverage</label>
        <input id="lev" type="number" step="1" value="5">
      </div>
    </div>

    <div class="row">
      <div>
        <label>Position side</label>
        <select id="position_side">
          <option value="BOTH" selected>BOTH (One-Way)</option>
          <option value="LONG">LONG (Hedge)</option>
          <option value="SHORT">SHORT (Hedge)</option>
        </select>
      </div>
      <div>
        <label>Budget (optional)</label>
        <input id="budget" type="number" step="0.01" placeholder="0 = ignore">
      </div>
    </div>
  </fieldset>

  <fieldset>
    <legend>TP/SL (optional)</legend>
    <div class="row">
      <div>
        <label>TP1</label>
        <input id="tp1" type="number" step="0.0001" placeholder="price or leave empty">
      </div>
      <div>
        <label>TP2</label>
        <input id="tp2" type="number" step="0.0001">
      </div>
    </div>
    <div class="row">
      <div>
        <label>TP3</label>
        <input id="tp3" type="number" step="0.0001">
      </div>
      <div>
        <label>SL</label>
        <input id="sl" type="number" step="0.0001">
      </div>
    </div>
  </fieldset>

  <fieldset>
    <legend>Meta</legend>
    <label>Note (free text)</label>
    <input id="note" placeholder="will be prefixed with [mode: ...] automatically">
    <small class="hint">המערכת תוסיף בתחילת ההערה שלך תג כמו [mode: MARKET] / [mode: HYBRID] / [mode: AUTO]</small>

    <div class="kvs">
      <div>API Base:</div><div id="kv_base"></div>
      <div>Token present:</div><div id="kv_tok"></div>
    </div>
  </fieldset>

  <div class="btns">
    <button class="variant" onclick="send('MARKET')">Create ticket – MARKET</button>
    <button class="warn" onclick="send('HYBRID')">Create ticket – HYBRID</button>
    <button class="alt" onclick="send('AUTO')">Create ticket – AUTO</button>
  </div>

  <div id="out" class="out" hidden></div>

<script>
async function send(mode){
  const el = id => document.getElementById(id);
  const payload = {
    symbol: (el('symbol').value||'').toUpperCase(),
    side: el('side').value,
    qty: Number(el('qty').value||0),
    leverage: Number(el('lev').value||0),
    position_side: el('position_side').value,
    budget: Number(el('budget').value||0) || 0,
    tp1: el('tp1').value? Number(el('tp1').value): null,
    tp2: el('tp2').value? Number(el('tp2').value): null,
    tp3: el('tp3').value? Number(el('tp3').value): null,
    sl:  el('sl').value?  Number(el('sl').value):  null,
    note: `[mode: ${mode}] ` + (el('note').value||'')
  };

  if(!payload.symbol || !payload.side || !(payload.qty>0) || !(payload.leverage>0)){
    show({ok:false, error:"Missing required fields (symbol/side/qty/leverage)."});
    return;
  }

  try{
    const base = (window.API_BASE || '').replace(/\\/$/,'');
    const url  = base ? (base + '/ops/ticket') : '/ops/ticket';
    const headers = {'content-type':'application/json'};
    if(window.API_TOKEN){
      headers['Authorization'] = 'Bearer ' + window.API_TOKEN;
      headers['x-api-key'] = window.API_TOKEN; // כולל גם X-API-Key לבטוח
    }
    const res  = await fetch(url, {
      method: 'POST',
      headers,
      body: JSON.stringify(payload)
    });
    let data;
    try{ data = await res.json(); }catch(e){ data = {ok:false,status:res.status,error:'Non-JSON response'}; }
    if(data && data.approve_url){
      data.quick = `Approve: ${data.approve_url}\\nReject : ${data.reject_url}`;
    }
    if(!res.ok){
      data = data || {};
      data.ok = false;
      data.http_status = res.status;
    }
    show(data);
  }catch(e){
    show({ok:false, error:String(e)});
  }
}

function show(obj){
  const out = document.getElementById('out');
  out.hidden = false;
  out.textContent = JSON.stringify(obj, null, 2);
}

window.API_BASE = '%API_BASE%';
window.API_TOKEN = '%API_TOKEN%';

document.getElementById('kv_base').textContent = window.API_BASE || '(relative)';
document.getElementById('kv_tok').textContent = window.API_TOKEN ? 'yes' : 'no';
</script>
"""

@router.get("/ops/ui", response_class=HTMLResponse, summary="Simple HTML page to create approval tickets")
async def ops_ui():
    html = HTML_PAGE.replace("%API_BASE%", API_BASE or "").replace("%API_TOKEN%", API_TOKEN or "")
    return HTMLResponse(html)

@router.post("/ops/ui/ticket")
async def ui_proxy(payload: dict = Body(...)):
    """
    נתיב שירות פנימי: אם יש PUBLIC_HOST – נשלח לשם עם הטוקן מהשרת.
    אם אין – נקרא לפונקציה הפנימית של יצירת טיקט (לולאה מקומית).
    """
    base = API_BASE or ""
    url = (base.rstrip("/") + "/ops/ticket") if base else "/ops/ticket"

    # מצב לולאה מקומית
    if not base:
        try:
            from .ops_approve import create_ticket  # type: ignore
            return await create_ticket(payload)
        except Exception as e:
            return JSONResponse(status_code=500, content={"ok": False, "error": "local_create_failed", "detail": str(e)})

    # פרוקסי עם טוקן
    try:
        headers = {"Content-Type":"application/json"}
        if API_TOKEN:
            headers["Authorization"] = f"Bearer {API_TOKEN}"
            headers["X-API-Key"] = API_TOKEN
        async with httpx.AsyncClient(timeout=15.0) as cli:
            r = await cli.post(url, headers=headers, content=json.dumps(payload))
            ctype = r.headers.get("content-type","")
            if "application/json" in ctype.lower():
                return JSONResponse(status_code=r.status_code, content=r.json())
            else:
                return JSONResponse(status_code=r.status_code, content={"ok":False,"error":"upstream_non_json","body":r.text})
    except Exception as e:
        return JSONResponse(status_code=502, content={"ok": False, "error": "proxy_failed", "detail": str(e)})



