# routes/ops_ui.py
from __future__ import annotations
from fastapi import APIRouter, Body
from fastapi.responses import HTMLResponse, JSONResponse
import os, json, httpx

router = APIRouter(tags=["ops-ui"])

API_BASE = (os.getenv("PUBLIC_HOST", "") or "").rstrip("/")
API_KEY  = os.getenv("API_KEY") or os.getenv("API_BEARER_TOKEN") or os.getenv("API_TOKEN") or ""

HTML_PAGE = """<!doctype html>
<meta charset="utf-8">
<title>Ops Ticket UI</title>
<style>
  :root{--bg:#0b1020;--card:#121a34;--txt:#e8ecff;--muted:#9fb0ff;--pri:#4c7dff;--pri2:#31c48d;--warn:#ffae42}
  *{box-sizing:border-box}
  body{font-family:ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
       background:linear-gradient(180deg,#0b1020 0%,#0e1530 100%);color:var(--txt);margin:0}
  .wrap{max-width:860px;margin:32px auto;padding:0 16px}
  h1{font-size:22px;margin:0 0 14px}
  .card{background:var(--card);border:1px solid rgba(255,255,255,.06);border-radius:16px;padding:16px;box-shadow:0 10px 30px rgba(0,0,0,.25)}
  fieldset{border:1px dashed rgba(255,255,255,.08);padding:16px;border-radius:14px;margin:0 0 16px}
  legend{color:var(--muted)}
  label{display:block;margin:8px 0 6px;font-weight:600;color:#d7ddff}
  input,select{width:100%;padding:10px 12px;border:1px solid rgba(255,255,255,.12);border-radius:10px;background:#0d1430;color:var(--txt);outline:none}
  .row{display:grid;grid-template-columns:1fr 1fr;gap:12px}
  @media (max-width:700px){.row{grid-template-columns:1fr}}
  .btns{display:flex;gap:10px;flex-wrap:wrap;margin-top:12px}
  button{padding:11px 14px;border:0;border-radius:12px;background:var(--pri);color:#fff;cursor:pointer;font-weight:700}
  button.variant{background:var(--pri2)}
  button.warn{background:var(--warn);color:#1c1302}
  button.alt{background:#6b6ee0}
  .out{white-space:pre-wrap;background:#0a1028;border:1px solid rgba(255,255,255,.08);border-radius:10px;padding:12px;margin-top:14px}
  small.hint{color:var(--muted)}
</style>
<body>
  <div class="wrap">
    <h1>Ops • Create Ticket</h1>
    <div class="card">

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
    <small class="hint">המערכת תוסיף בתחילת ההערה תג כמו [mode: MARKET] / [mode: HYBRID] / [mode: AUTO]</small>
  </fieldset>

  <div class="btns">
    <button class="variant" onclick="send('MARKET')">Create ticket – MARKET</button>
    <button class="warn" onclick="send('HYBRID')">Create ticket – HYBRID</button>
    <button class="alt" onclick="send('AUTO')">Create ticket – AUTO</button>
  </div>

  <div id="out" class="out" hidden></div>
  </div></div>

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
    const url  = base ? (base + '/ops/ticket') : '/ops/ui/ticket'; // ברירת מחדל דרך פרוקסי
    const headers = {
      'content-type': 'application/json',
      ...(window.API_KEY ? {'x-api-key': window.API_KEY} : {})
    };
    const res  = await fetch(url, { method: 'POST', headers, body: JSON.stringify(payload) });
    const data = await res.json();
    if(data && data.approve_url){ data.quick = `Approve: ${data.approve_url}\\nReject : ${data.reject_url}`; }
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
window.API_KEY  = '%API_KEY%';
</script>
"""

@router.get("/ops/ui", response_class=HTMLResponse, summary="Simple HTML page to create approval tickets")
async def ops_ui():
    html = HTML_PAGE.replace("%API_BASE%", API_BASE or "").replace("%API_KEY%", API_KEY or "")
    return HTMLResponse(html)

@router.post("/ops/ui/ticket")
async def ui_proxy(payload: dict = Body(...)):
    """
    פרוקסי צד-שרת: אם יש API_BASE נקרא לשירות הראשי.
    אחרת נייבא את יוצר הטיקט המקומי (routes.ops_approve.create_ticket).
    תמיד שולחים x-api-key אם מוגדר.
    """
    base = API_BASE or ""
    try:
        if base:
            url = base.rstrip("/") + "/ops/ticket"
            headers = {"Content-Type":"application/json"}
            if API_KEY:
                headers["x-api-key"] = API_KEY
            async with httpx.AsyncClient(timeout=12.0) as cli:
                r = await cli.post(url, headers=headers, content=json.dumps(payload))
                return JSONResponse(status_code=r.status_code, content=r.json())
        else:
            from .ops_approve import create_ticket  # type: ignore
            return await create_ticket(payload)
    except Exception as e:
        return JSONResponse(status_code=502, content={"ok": False, "error": "proxy_failed", "detail": str(e)})

