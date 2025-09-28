# routes/ops_ui.py
from __future__ import annotations
from fastapi import APIRouter, Body
from fastapi.responses import HTMLResponse, JSONResponse
import os
import json
import httpx

router = APIRouter(tags=["ops-ui"])

API_BASE = os.getenv("PUBLIC_HOST", "").rstrip("/")
API_TOKEN = os.getenv("API_BEARER_TOKEN") or os.getenv("API_TOKEN") or ""

HTML_PAGE = """<!doctype html>
<meta charset="utf-8">
<title>Ops Ticket UI</title>
<style>
  body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;max-width:780px;margin:32px auto;padding:0 16px;line-height:1.4}
  h1{font-size:20px;margin:0 0 16px}
  fieldset{border:1px solid #ddd;padding:16px;border-radius:10px;margin:0 0 16px}
  label{display:block;margin:8px 0 4px;font-weight:600}
  input,select{width:100%;padding:8px 10px;border:1px solid #ccc;border-radius:8px;font:inherit}
  .row{display:grid;grid-template-columns:1fr 1fr;gap:12px}
  .btns{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}
  button{padding:10px 14px;border:0;border-radius:10px;background:#222;color:#fff;cursor:pointer}
  button.variant{background:#0a7}
  button.warn{background:#08c}
  button.alt{background:#666}
  .out{white-space:pre-wrap;background:#f7f7f7;border:1px solid #eee;border-radius:8px;padding:12px;margin-top:14px}
  small.hint{color:#666}
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
    const base = (window.API_BASE || '%API_BASE%').replace(/\\/$/,'');
    const url  = base ? (base + '/ops/ticket') : '/ops/ticket';
    const res  = await fetch(url, {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        ...(window.API_TOKEN ? {'Authorization': 'Bearer '+ window.API_TOKEN} : {})
      },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if(data && data.approve_url){
      data.quick = `Approve: ${data.approve_url}\\nReject : ${data.reject_url}`;
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
</script>
"""

@router.get("/ops/ui", response_class=HTMLResponse, summary="Simple HTML page to create approval tickets")
async def ops_ui():
    html = HTML_PAGE.replace("%API_BASE%", API_BASE or "").replace("%API_TOKEN%", API_TOKEN or "")
    return HTMLResponse(html)

@router.post("/ops/ui/ticket")
async def ui_proxy(payload: dict = Body(...)):
    base = API_BASE or ""
    url = (base.rstrip("/") + "/ops/ticket") if base else "/ops/ticket"
    if not base:
        from .ops_approve import create_ticket  # type: ignore
        return await create_ticket(payload)
    try:
        headers = {"Content-Type":"application/json"}
        if API_TOKEN:
            headers["Authorization"] = f"Bearer {API_TOKEN}"
        async with httpx.AsyncClient(timeout=12.0) as cli:
            r = await cli.post(url, headers=headers, content=json.dumps(payload))
            return JSONResponse(status_code=r.status_code, content=r.json())
    except Exception as e:
        return JSONResponse(status_code=502, content={"ok": False, "error": "proxy_failed", "detail": str(e)})

