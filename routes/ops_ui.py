# routes/ops_ui.py
from __future__ import annotations
from typing import Optional, List, Callable, Any, Tuple
from fastapi import APIRouter, Body, Query, Request, HTTPException, Depends
from fastapi.responses import HTMLResponse, JSONResponse
import os, json, httpx

# shared helpers
from .orders_utils import (
    csv_list, norm_upper, as_float, as_int, filter_by_status, filter_by_side,
    fetch_orders_multi, sort_key_factory, apply_sort, filter_price_range,
    filter_qty_range, filter_time_range, filter_client_order_id, token_ok
)

router = APIRouter(tags=["ops-ui"])

API_BASE = (os.getenv("PUBLIC_HOST", "") or "").rstrip("/")
API_KEY  = (
    os.getenv("API_KEY")
    or os.getenv("API_BEARER_TOKEN")
    or os.getenv("API_TOKEN")
    or ""
)

DEFAULT_QTY_STEP = os.getenv("DEFAULT_QTY_STEP", "0.001")
OPS_BEARER_TOKEN = os.getenv("API_BEARER_TOKEN", "") or os.getenv("API_TOKEN", "")

def _require_ops_bearer(request: Request):
    """
    אם הוגדר טוקן – נדרשת הזדהות.
    מתקבל או Authorization: Bearer <token> או כותרת x-api-key עם אותו הטוקן.
    """
    tok = OPS_BEARER_TOKEN
    if not tok:
        return
    auth = request.headers.get("Authorization") or ""
    xkey = request.headers.get("x-api-key") or ""
    if (auth.startswith("Bearer ") and auth.split(" ", 1)[1] == tok) or (xkey == tok):
        return
    raise HTTPException(status_code=401, detail="unauthorized")

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
  small.hint.warn{color:#ff7b63;font-weight:700}
  .inline-btn{margin-top:6px; display:inline-block; padding:6px 10px; border-radius:10px; background:#24305a; color:#cfe1ff; cursor:pointer; font-size:12px}
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
        <div id="use_suggested_qty" class="inline-btn" style="display:none" title="הדבק כמות מוצעת">Use suggested qty</div>
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
        <small id="budget_hint" class="hint"></small>
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
let LAST_PRICE = null;
const STEP_CACHE = {};
window.DEFAULT_QTY_STEP = Number('%DEFAULT_QTY_STEP%') || 0.001;
function apiHeaders(){ return { ...(window.API_KEY ? {'x-api-key': window.API_KEY} : {}) }; }
async function fetchJSON(url){ const r = await fetch(url, { headers: apiHeaders() }); return r.ok ? r.json() : null; }
async function fetchPrice(symbol){
  const base = (window.API_BASE || '').replace(/\/$/,''); if(!base || !symbol) return null;
  try{
    const data = await fetchJSON(base + '/price/' + encodeURIComponent(symbol.toUpperCase()));
    if(data && data.ok && data.price!=null){ LAST_PRICE = Number(data.price); return LAST_PRICE; }
  }catch(e){}
  return null;
}
function parseStepFromExchangeInfo(symbol, exInfo){
  try{
    if(!exInfo) return null;
    if (Array.isArray(exInfo.symbols)) {
      const s = exInfo.symbols.find(x => (x.symbol||'').toUpperCase() === symbol.toUpperCase());
      const f = s && Array.isArray(s.filters) ? s.filters.find(ff => (ff.filterType||'')==='LOT_SIZE') : null;
      const step = f && (f.stepSize || f.step_size);
      return step ? Number(step) : null;
    }
    const s = exInfo[symbol] || exInfo[symbol.toUpperCase()];
    if (s && (s.stepSize || s.step_size)) return Number(s.stepSize || s.step_size);
  }catch(e){} return null;
}
function parseStepFromList(symbol, list){
  try{
    if(!Array.isArray(list)) return null;
    const row = list.find(x => (x.symbol||'').toUpperCase() === symbol.toUpperCase());
    if(!row) return null;
    const cand = row.step || row.qty_step || row.lotStep || row.stepSize || row.step_size;
    return cand ? Number(cand) : null;
  }catch(e){} return null;
}
async function fetchQtyStep(symbol){
  const base = (window.API_BASE || '').replace(/\/$/,''); if(!base || !symbol) return window.DEFAULT_QTY_STEP;
  const sym = symbol.toUpperCase(); if (STEP_CACHE[sym]) return STEP_CACHE[sym];
  let step = null;
  try{
    const data1 = await fetchJSON(base + '/market/info/' + encodeURIComponent(sym));
    if (data1) {
      if (data1.stepSize || data1.step_size) step = Number(data1.stepSize || data1.step_size);
      else if (data1.filters && data1.filters.LOT_SIZE && (data1.filters.LOT_SIZE.stepSize||data1.filters.LOT_SIZE.step_size)) {
        step = Number(data1.filters.LOT_SIZE.stepSize || data1.filters.LOT_SIZE.step_size);
      } else { step = parseStepFromExchangeInfo(sym, data1); }
    }
  }catch(e){}
  if (step==null){
    try{ const list = await fetchJSON(base + '/market/symbols'); step = parseStepFromList(sym, list); }catch(e){}
  }
  if (step==null){
    try{ const exInfo = await fetchJSON(base + '/market/exchangeInfo'); step = parseStepFromExchangeInfo(sym, exInfo); }catch(e){}
  }
  if (step==null || !(step>0)) step = window.DEFAULT_QTY_STEP;
  STEP_CACHE[sym] = step; return step;
}
function roundQty(qty, step){ step = Number(step)||0.001; return Math.floor(qty/step)*step; }
function show(obj){ const out = document.getElementById('out'); out.hidden = false; out.textContent = JSON.stringify(obj, null, 2); }
async function updateBudgetHint(){
  const sym = document.getElementById('symbol').value.trim().toUpperCase();
  const lev = Number(document.getElementById('lev').value||0);
  const bud = Number(document.getElementById('budget').value||0);
  const hintEl = document.getElementById('budget_hint');
  const suggBtn = document.getElementById('use_suggested_qty');
  hintEl.classList.remove('warn'); suggBtn.style.display = 'none'; suggBtn.onclick = null;
  if(!sym || lev<=0){ hintEl.textContent=''; return; }
  const [price, step] = await Promise.all([(LAST_PRICE==null ? fetchPrice(sym) : Promise.resolve(LAST_PRICE)), fetchQtyStep(sym),]);
  if(!price || !step){ hintEl.textContent=''; return; }
  const minNotional = price * step; const minBudget = minNotional / lev; const suggested = (bud>0) ? roundQty((bud*lev)/price, step) : 0;
  const parts = [`Price≈ ${price.toFixed(2)} | step=${step}`, `Min budget≈ ${minBudget.toFixed(2)} USDT`, (bud>0 ? `Suggested qty≈ ${suggested}` : '')].filter(Boolean);
  hintEl.textContent = parts.join(' · ');
  if(bud>0 && suggested>0){ suggBtn.style.display = 'inline-block'; suggBtn.onclick = ()=>{ document.getElementById('qty').value = suggested; }; }
  if(bud>0 && bud < minBudget){ hintEl.classList.add('warn'); }
}
async function autoFillQtyIfNeeded(payload){
  if((!payload.qty || payload.qty<=0) && payload.budget>0 && payload.leverage>0){
    const step = await fetchQtyStep(payload.symbol);
    const price = LAST_PRICE ?? await fetchPrice(payload.symbol);
    if(price){ const raw = (payload.budget * payload.leverage) / price; payload.qty = roundQty(raw, step); }
  }
}
['symbol','lev','budget'].forEach(id=>{ const el = document.getElementById(id); el.addEventListener('input', ()=>updateBudgetHint()); el.addEventListener('change', ()=>updateBudgetHint()); });
window.addEventListener('load', ()=>updateBudgetHint());
async function send(mode){
  const el = id => document.getElementById(id);
  const payload = {
    symbol: (el('symbol').value||'').toUpperCase(),
    side: el('side').value,
    qty: Number(el('qty').value||0),
    leverage: Number(el('lev').value||0),
    position_side: el('position_side').value,
    budget: Number(el('budget').value)||0,
    tp1: el('tp1').value? Number(el('tp1').value): null,
    tp2: el('tp2').value? Number(el('tp2').value): null,
    tp3: el('tp3').value? Number(el('tp3').value): null,
    sl:  el('sl').value?  Number(el('sl').value):  null,
    note: `[mode: ${mode}] ` + (el('note').value||'')
  };
  await autoFillQtyIfNeeded(payload);
  if(!payload.symbol || !payload.side || !(payload.leverage>0)){ show({ok:false, error:"Missing required fields (symbol/side/leverage)."}); return; }
  if(!(payload.qty>0) && !(payload.budget>0)){ show({ok:false, error:"Provide qty or budget (or let auto-qty compute)."}); return; }
  try{
    const base = (window.API_BASE || '%API_BASE%').replace(/\\/$,'');
    const url  = base ? (base + '/ops/ticket') : '/ops/ui/ticket';
    const headers = { 'content-type': 'application/json', ...(window.API_KEY ? {'x-api-key': window.API_KEY} : {}) };
    const res  = await fetch(url, { method: 'POST', headers, body: JSON.stringify(payload) });
    const data = await res.json();
    if(data && data.approve_url){ data.quick = `Approve: ${data.approve_url}\\nReject : ${data.reject_url}`; }
    show(data);
  }catch(e){ show({ok:false, error:String(e)}); }
}
window.API_BASE = '%API_BASE%'; window.API_KEY  = '%API_KEY%';
</script>
"""

@router.get("/ops/ui", response_class=HTMLResponse, summary="Simple HTML page to create approval tickets", dependencies=[Depends(_require_ops_bearer)])
async def ops_ui():
  # לא מזרימים מפתח API לדפדפן כדי למנוע דליפה
  html = (
      HTML_PAGE
      .replace("%API_BASE%", API_BASE or "")
      .replace("%API_KEY%",  "")  # לא מטמיעים מפתח לקוח
      .replace("%DEFAULT_QTY_STEP%", str(DEFAULT_QTY_STEP))
  )
  return HTMLResponse(html)

@router.post("/ops/ui/ticket", dependencies=[Depends(_require_ops_bearer)])
async def ui_proxy(request: Request, payload: dict = Body(...)):
  """
  Proxy בצד שרת: אם API_BASE מוגדר – נעביר לשירות הראשי.
  אחרת נקרא ליוצר טיקט מקומי. מעבירים Authorization אם הגיע, וגם x-api-key אם הוגדר בצד ה-UI.
  """
  base = API_BASE or ""
  try:
    if base:
      url = base.rstrip("/") + "/ops/ticket"
      headers = {"Content-Type": "application/json"}
      # העברת Bearer מהמזמין, אם קיים
      auth = request.headers.get("Authorization")
      if auth:
        headers["Authorization"] = auth
      # אם יש מפתח מערכת – נוכל להעבירו כ-x-api-key לשרת היעד (במידה והוא מצפה לכך)
      if API_KEY:
        headers["x-api-key"] = API_KEY
      async with httpx.AsyncClient(timeout=12.0) as cli:
        r = await cli.post(url, headers=headers, content=json.dumps(payload))
        try:
          content = r.json()
        except Exception:
          content = {"ok": (r.status_code < 400), "status": r.status_code, "text": r.text}
        return JSONResponse(status_code=r.status_code, content=content)
    else:
      from .ops_approve import create_ticket  # type: ignore
      return await create_ticket(payload)
  except Exception as e:
    return JSONResponse(status_code=502, content={"ok": False, "error": "proxy_failed", "detail": str(e)})

# ====== HTML (basic filters) ======
@router.get(
  "/ops/ui/orders",
  response_class=HTMLResponse,
  summary="List open futures orders (HTML)",
  dependencies=[Depends(_require_ops_bearer)],
)
async def ops_ui_orders(
  symbol: Optional[str] = Query(None, description="e.g. BTCUSDT (single)"),
  symbols: Optional[List[str]] = Query(None, description="repeatable ?symbols=BTCUSDT&symbols=ETHUSDT or CSV"),
  status: Optional[List[str]] = Query(None, description="filter by status: e.g. NEW,FILLED or repeatable"),
  side: Optional[List[str]] = Query(None, description="filter by side: BUY/SELL (repeatable or CSV)"),
):
  try:
    from utils.binance_client import get_open_orders  # type: ignore
  except Exception as e:
    return HTMLResponse(
      f"<!doctype html><meta charset='utf-8'><body style='font-family:sans-serif;margin:2rem'>"
      f"<h2>Open Orders</h2><p style='color:#b91c1c'>binance_client unavailable: {e}</p></body>"
    )

  sym_list: List[str] = []
  if symbols:
    for item in symbols:
      sym_list.extend(csv_list(item))
  elif symbol:
    sym_list = [norm_upper(symbol)]

  try:
    orders = fetch_orders_multi(sym_list)
  except Exception as e:
    return HTMLResponse(
      f"<!doctype html><meta charset='utf-8'><body style='font-family:sans-serif;margin:2rem'>"
      f"<h2>Open Orders</h2><p style='color:#b91c1c'>Error fetching orders: {str(e)}</p></body>"
    )

  status_list: List[str] = []
  if status:
    for item in status: status_list.extend(csv_list(item))
  side_list: List[str] = []
  if side:
    for item in side: side_list.extend(csv_list(item))

  orders = filter_by_status(orders, status_list)
  orders = filter_by_side(orders, side_list)

  def esc(v):
    return ("" if v is None else str(v)).replace("<", "&lt;").replace(">", "&gt;")

  if not orders:
    filt_sym = ", ".join(sym_list) if sym_list else "ALL"
    filt_sts = ", ".join([s.upper() for s in status_list]) if status_list else "ANY"
    filt_side = ", ".join([s.upper() for s in side_list]) if side_list else "ANY"
    return HTMLResponse(
      f"<!doctype html><meta charset='utf-8'><body style='font-family:sans-serif;margin:2rem'>"
      f"<h2>Open Orders</h2>"
      f"<p>No open orders for <b>{esc(filt_sym)}</b> with status <b>{esc(filt_sts)}</b> and side <b>{esc(filt_side)}</b>.</p>"
      f"<p style='color:#777'>Tips: "
      f"<code>?symbol=BTCUSDT</code> | <code>?symbols=BTCUSDT,ETHUSDT</code> | <code>?status=NEW</code> | <code>?side=BUY</code></p>"
      f"</body>"
    )

  rows = []
  for o in orders:
    rows.append(
      "<tr>"
      f"<td>{esc(o.get('orderId'))}</td>"
      f"<td>{esc(o.get('symbol'))}</td>"
      f"<td>{esc(o.get('side'))}</td>"
      f"<td>{esc(o.get('type'))}</td>"
      f"<td>{esc(o.get('origQty') or o.get('orig_quantity') or o.get('quantity'))}</td>"
      f"<td>{esc(o.get('price') or o.get('avgPrice'))}</td>"
      f"<td>{esc(o.get('reduceOnly'))}</td>"
      f"<td>{esc(o.get('status'))}</td>"
      "</tr>"
    )

  html = (
    "<!doctype html><meta charset='utf-8'>"
    "<title>Open Orders</title>"
    "<style>"
    "body{font-family:ui-sans-serif,system-ui;max-width:1100px;margin:2rem auto;padding:0 1rem;line-height:1.45}"
    "table{border-collapse:collapse;width:100%;border:1px solid #eee}"
    "th,td{padding:.4rem .6rem;text-align:left;border-bottom:1px solid #f2f2f2}"
    "thead tr{background:#fafafa}"
    "</style><body>"
    "<h2 style='margin:.2rem 0 1rem 0'>Open Orders</h2>"
    "<table><thead><tr>"
    "<th>OrderId</th><th>Symbol</th><th>Side</th><th>Type</th>"
    "<th>Qty</th><th>Price</th><th>ReduceOnly</th><th>Status</th>"
    "</tr></thead>"
    f"<tbody>{''.join(rows)}</tbody></table>"
    "<p style='color:#777;margin-top:.8rem'>"
    "סינון: <code>?symbol=BTCUSDT</code> | "
    "<code>?symbols=BTCUSDT,ETHUSDT</code> | "
    "<code>?status=NEW</code> | "
    "<code>?side=BUY,SELL</code>"
    "</p>"
    "</body>"
  )
  return HTMLResponse(html)

# ====== JSON (filters, sort, pagination) ======
@router.get(
  "/ops/ui/orders.json",
  response_class=JSONResponse,
  summary="List open futures orders (JSON)",
  dependencies=[Depends(_require_ops_bearer)],
)
async def ops_ui_orders_json(
  symbol: Optional[str] = Query(None, description="e.g. BTCUSDT (single)"),
  symbols: Optional[List[str]] = Query(None, description="repeatable ?symbols=BTCUSDT&symbols=ETHUSDT or CSV"),
  status: Optional[List[str]] = Query(None, description="filter by status: e.g. NEW,FILLED or repeatable"),
  side: Optional[List[str]] = Query(None, description="filter by side: BUY/SELL (repeatable or CSV)"),
  # Range filters
  min_price: Optional[float] = Query(None, description="minimum order price (inclusive)"),
  max_price: Optional[float] = Query(None, description="maximum order price (inclusive)"),
  min_qty: Optional[float] = Query(None, description="minimum origQty/quantity (inclusive)"),
  max_qty: Optional[float] = Query(None, description="maximum origQty/quantity (inclusive)"),
  since_ts: Optional[int] = Query(None, description="min updateTime/time (ms, inclusive)"),
  until_ts: Optional[int] = Query(None, description="max updateTime/time (ms, inclusive)"),
  # Client order id filters
  client_order_id: Optional[str] = Query(None, description="exact match for clientOrderId/origClientOrderId"),
  client_order_like: Optional[str] = Query(None, description="substring match, case-insensitive"),
  # Sorting
  sort_by: Optional[List[str]] = Query(None, description="repeatable or CSV, e.g. sort_by=updateTime&sort_by=symbol or sort_by=updateTime,symbol"),
  order: Optional[str] = Query("desc", description="asc|desc (applies to all sort_by fields)"),
  # Pagination
  limit: Optional[int] = Query(100, ge=1, le=1000, description="items per page"),
  offset: Optional[int] = Query(0, ge=0, description="start index (0-based)"),
  page: Optional[int] = Query(None, ge=1, description="1-based page number (alias)"),
  per_page: Optional[int] = Query(None, ge=1, le=1000, description="items per page (alias)"),
):
  sym_list: List[str] = []
  if symbols:
    for item in symbols:
      sym_list.extend(csv_list(item))
  elif symbol:
    sym_list = [norm_upper(symbol)]

  try:
    orders = fetch_orders_multi(sym_list)
  except Exception as e:
    return JSONResponse(
      status_code=503,
      content={"ok": False, "error": "binance_client_unavailable_or_fetch_failed", "detail": str(e)},
    )

  status_list: List[str] = []
  if status:
    for item in status: status_list.extend(csv_list(item))
  side_list: List[str] = []
  if side:
    for item in side: side_list.extend(csv_list(item))

  orders = filter_by_status(orders, status_list)
  orders = filter_by_side(orders, side_list)
  orders = filter_price_range(orders, min_price, max_price)
  orders = filter_qty_range(orders, min_qty, max_qty)
  orders = filter_time_range(orders, since_ts, until_ts)
  orders = filter_client_order_id(orders, client_order_id, client_order_like)

  sort_fields: List[str] = []
  if sort_by:
    for item in sort_by:
      sort_fields.extend(csv_list(item))
  orders = apply_sort(orders, sort_fields, (order or "desc"))

  total = len(orders)

  eff_per_page = int(per_page or limit or 100)
  eff_page = int(page) if page is not None else None
  if eff_page is not None:
    eff_offset = (eff_page - 1) * eff_per_page
  else:
    eff_offset = int(offset or 0)
  if eff_offset < 0: eff_offset = 0
  if eff_per_page < 1: eff_per_page = 1
  end = min(total, eff_offset + eff_per_page)
  sliced = orders[eff_offset:end]

  def pick(o: dict, *keys: str) -> dict:
    return {k: o.get(k) for k in keys}

  items = [
    {
      **pick(
        o,
        "orderId","symbol","side","type","status","reduceOnly",
        "timeInForce","activatePrice","priceRate",
      ),
      "price": o.get("price") or o.get("avgPrice"),
      "origQty": o.get("origQty") or o.get("orig_quantity") or o.get("quantity"),
      "executedQty": o.get("executedQty") or o.get("executed_quantity"),
      "clientOrderId": o.get("clientOrderId") or o.get("origClientOrderId"),
      "updateTime": o.get("updateTime") or o.get("time"),
    }
    for o in sliced
  ]

  has_prev = eff_offset > 0
  has_next = end < total
  prev_offset = max(0, eff_offset - eff_per_page) if has_prev else None
  next_offset = end if has_next else None
  eff_page_num = (eff_offset // eff_per_page) + 1
  total_pages = (total + eff_per_page - 1) // eff_per_page if eff_per_page else 1

  return JSONResponse(
    content={
      "ok": True,
      "symbols": sym_list or None,
      "status_filter": [s.upper() for s in status_list] or None,
      "side_filter": [s.upper() for s in side_list] or None,
      "filters": {
        "min_price": min_price, "max_price": max_price,
        "min_qty": min_qty, "max_qty": max_qty,
        "since_ts": since_ts, "until_ts": until_ts,
        "client_order_id": client_order_id,
        "client_order_like": client_order_like,
      },
      "sort_by": sort_fields or ["updateTime"],
      "order": (order or "desc").lower(),
      "count": len(items),
      "items": items,
      "total": total,
      "limit": eff_per_page,
      "offset": eff_offset,
      "end_offset": end,
      "has_prev": has_prev,
      "has_next": has_next,
      "prev_offset": prev_offset,
      "next_offset": next_offset,
      "page": eff_page_num,
      "per_page": eff_per_page,
      "total_pages": total_pages,
    }
  )




