# routes/visual_stream.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import os, asyncio, json
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Header, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, StreamingResponse

from utils.redis_helper import get_redis

router = APIRouter(prefix="/public", tags=["Public Feed"])

_POS_EVENTS_KEY = os.getenv("POS_EVENTS_KEY", "pos:events")
_POS_EVENTS_CHAN = os.getenv("POS_EVENTS_CHAN", "pos:events:chan")
_SSE_HEARTBEAT_SEC = int(os.getenv("PUBLIC_SSE_HEARTBEAT_SEC", "20"))

async def _sse_event(event: str, data: dict | list) -> bytes:
    payload = f"event: {event}\n" + "data: " + json.dumps(data, ensure_ascii=False, separators=(",",":")) + "\n\n"
    return payload.encode("utf-8")

async def _sse_comment(msg: str) -> bytes:
    return (f": {msg}\n\n").encode("utf-8")

# ====== SSE: תמונת מצב פוזיציות ======
@router.get("/sse-positions")
async def sse_positions(request: Request):
    r = await get_redis()
    if not r:
        return PlainTextResponse("redis_unavailable", status_code=503)

    async def gen():
        last_ping = 0
        while True:
            if await request.is_disconnected(): break
            try:
                raw = await r.get("pos:all")
                if raw:
                    doc = json.loads(raw)
                    yield await _sse_event("positions", doc)
            except Exception:
                pass
            # heartbeat למניעת idle timeouts
            now = asyncio.get_event_loop().time()
            if now - last_ping > _SSE_HEARTBEAT_SEC:
                last_ping = now
                yield await _sse_comment("hb")
            await asyncio.sleep(2)
    headers = {
        "Cache-Control": "no-cache",
        "Content-Type": "text/event-stream",
        "Connection": "keep-alive",
    }
    return StreamingResponse(gen(), headers=headers)

# ====== SSE: אירועי ניהול חכם (PUBSUB + BACKLOG) ======
@router.get("/sse-pos-events")
async def sse_pos_events(request: Request):
    r = await get_redis()
    if not r:
        return PlainTextResponse("redis_unavailable", status_code=503)

    async def gen():
        # שליחת BACKLOG ראשוני (עד 100 אחרונים)
        try:
            raw_list = await r.lrange(_POS_EVENTS_KEY, 0, 99)
            if raw_list:
                items = [json.loads(x) for x in raw_list][::-1]  # מהישן לחדש
                yield await _sse_event("pos_events_snapshot", items)
        except Exception:
            pass

        # הרשמה ל-PUBSUB
        pubsub = r.pubsub()
        await pubsub.subscribe(_POS_EVENTS_CHAN)

        last_ping = 0
        try:
            while True:
                if await request.is_disconnected(): break
                try:
                    msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                    if msg and msg.get("type") == "message":
                        data = msg.get("data")
                        if isinstance(data, (bytes, bytearray)):
                            data = data.decode("utf-8", "ignore")
                        try:
                            evt = json.loads(data)
                        except Exception:
                            evt = {"raw": data}
                        yield await _sse_event("pos_event", evt)
                except Exception:
                    pass
                # heartbeat
                now = asyncio.get_event_loop().time()
                if now - last_ping > _SSE_HEARTBEAT_SEC:
                    last_ping = now
                    yield await _sse_comment("hb")
                await asyncio.sleep(0.1)
        finally:
            try:
                await pubsub.unsubscribe(_POS_EVENTS_CHAN)
                await pubsub.close()
            except Exception:
                pass

    headers = {
        "Cache-Control": "no-cache",
        "Content-Type": "text/event-stream",
        "Connection": "keep-alive",
    }
    return StreamingResponse(gen(), headers=headers)

# ====== UI ======
@router.get("/positions/web")
async def positions_web():
    html = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Positions — Live</title>
<style>
:root{color-scheme:dark light}
body{font-family:system-ui,Segoe UI,Roboto,Arial,sans-serif;margin:0;background:#0b0d10;color:#e2e8f0}
.wrap{padding:16px}
h2{margin:0 0 8px 0}
.layout{display:grid;grid-template-columns:2fr 1fr;gap:14px}
@media (max-width: 980px){.layout{grid-template-columns:1fr}}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:12px}
.card{background:#111827;border:1px solid #1f2937;border-radius:12px;padding:12px}
h3{margin:0 0 6px 0;font-size:16px}
.badge{display:inline-block;padding:2px 6px;border-radius:6px;background:#1f2937;margin-left:6px}
.buy{color:#10b981}.sell{color:#ef4444}
.kv{display:grid;grid-template-columns:120px 1fr;gap:4px;font-size:13px}
small{color:#94a3b8}
table{width:100%;border-collapse:collapse;margin-top:6px;font-size:13px}
th,td{padding:4px 6px;border-bottom:1px solid #1f2937;text-align:left}
th{color:#93c5fd}
.aside{background:#0f172a;border:1px solid #1f2937;border-radius:12px;padding:10px;max-height:85vh;overflow:auto}
.ev{display:grid;grid-template-columns:86px 1fr;gap:6px;padding:6px;border-bottom:1px solid #1f2937}
.ev .sym{font-weight:600}
.ev .op{font-size:12px}
.ev .pill{display:inline-block;font-size:11px;border-radius:999px;padding:2px 8px;border:1px solid #334155}
.pill-info{background:#1e293b}.pill-ok{background:#0f3b2a}.pill-warn{background:#3b2b0f}
.arrow{display:inline-block;margin:0 6px}
.up{color:#10b981}.down{color:#ef4444}
</style>
</head><body>
<div class="wrap">
  <h2>Positions <small id="ts">–</small></h2>
  <div class="layout">
    <div>
      <div id="grid" class="grid"></div>
    </div>
    <div class="aside">
      <h3 style="margin:4px 0 8px 6px;">Smart-Manage Events</h3>
      <div id="evs"></div>
    </div>
  </div>
</div>
<script>
const grid = document.getElementById("grid");
const ts = document.getElementById("ts");
const evs = document.getElementById("evs");

function fmt(x,d=4){if(x==null)return "-"; const n=Number(x); return Number.isFinite(n)? n.toFixed(d): x}
function card(doc){
  const side = doc.side ? (doc.side==="BUY"?"buy":"sell") : "";
  const h = [
    `<div class="card">`,
    `<h3>${doc.symbol||""}${doc.side?` <span class="badge ${side}">${doc.side}</span>`:""}${doc.has_position?"":" <span class='badge'>flat</span>"}</h3>`,
    `<div class="kv"><div>Amt</div><div>${fmt(doc.amt,4)}</div><div>Entry</div><div>${fmt(doc.entry,4)}</div><div>Mark</div><div>${fmt(doc.mark,4)}</div><div>Lev</div><div>${doc.lev||"-"}</div><div>uPnL</div><div>${fmt(doc.uPnL,4)}</div></div>`,
  ];
  if (doc.be){h.push(`<div class="kv"><div>BE Δ (bps)</div><div>${fmt(doc.be.dist_bps,2)}</div></div>`)}
  if (doc.trail){h.push(`<div class="kv"><div>Trail gap (bps)</div><div>${fmt(doc.trail.gap_bps,2)}</div></div>`)}
  if (doc.tp && doc.tp.length){
    h.push(`<table><thead><tr><th>TP</th><th>Price</th><th>Qty</th></tr></thead><tbody>`);
    doc.tp.forEach(t=>{h.push(`<tr><td>${t.type}</td><td>${fmt(t.stopPrice||t.price,4)}</td><td>${fmt(t.qty,4)}</td></tr>`);});
    h.push(`</tbody></table>`);
  }
  if (doc.sl && doc.sl.length){
    h.push(`<table><thead><tr><th>SL</th><th>Price</th><th>Qty</th></tr></thead><tbody>`);
    doc.sl.forEach(t=>{h.push(`<tr><td>${t.type}</td><td>${fmt(t.stopPrice||t.price,4)}</td><td>${fmt(t.qty,4)}</td></tr>`);});
    h.push(`</tbody></table>`);
  }
  h.push(`</div>`);
  return h.join("");
}
function render(items){ grid.innerHTML = (items||[]).map(card).join(""); }
function tsfmt(sec){ try{return new Date(sec*1000).toISOString().replace('T',' ').slice(0,19)}catch{return sec} }

function evRow(e){
  const s = e.sym||"-";
  const op = e.op||"event";
  const when = tsfmt(e.ts||0);
  let body = "";
  if(op==="trail_move"){
    body = `<span class="pill pill-info">Trail</span> ${fmt(e.from,4)} <span class="arrow">→</span> ${fmt(e.to,4)}`;
  }else if(op==="sl_move"){
    body = `<span class="pill pill-warn">SL</span> ${fmt(e.from,4)} <span class="arrow">→</span> ${fmt(e.to,4)}`;
  }else if(op==="be_arm"){
    body = `<span class="pill pill-ok">BE arm</span> @ ${fmt(e.bps,2)} bps`;
  }else if(op==="be_move"){
    body = `<span class="pill pill-ok">BE move</span> ${fmt(e.from_bps,2)} <span class="arrow">→</span> ${fmt(e.to_bps,2)} bps`;
  }else if(op==="tp_place"){
    body = `<span class="pill pill-info">TP place${e.idx!=null?(" #"+e.idx):""}</span> ${fmt(e.price,4)} · qty ${fmt(e.qty,4)}`;
  }else if(op==="tp_hit"){
    body = `<span class="pill pill-info">TP hit${e.idx!=null?(" #"+e.idx):""}</span> ${fmt(e.price,4)} · qty ${fmt(e.qty,4)}`;
  }else if(op==="note"){
    body = `<span class="pill">Note</span> ${e.msg||""}`;
  }else{
    body = JSON.stringify(e);
  }
  return `<div class="ev"><div><div class="sym">${s}</div><div class="op"><small>${op}</small></div><div><small>${when}</small></div></div><div>${body}</div></div>`;
}
function evPrepend(e){
  const el = document.createElement("div");
  el.innerHTML = evRow(e);
  if(evs.firstChild){ evs.insertBefore(el.firstChild, evs.firstChild); }
  else { evs.appendChild(el.firstChild); }
}

// live positions
const evPos = new EventSource("/public/sse-positions");
evPos.addEventListener("positions", e=>{
  try{
    const d = JSON.parse(e.data);
    ts.textContent = "ts: " + tsfmt(d.ts||0);
    render(d.items||[]);
  }catch(_){}
});

// live pos-events
const evMgr = new EventSource("/public/sse-pos-events");
evMgr.addEventListener("pos_events_snapshot", e=>{
  try{
    const arr = JSON.parse(e.data)||[];
    evs.innerHTML = arr.map(evRow).join("");
  }catch(_){}
});
evMgr.addEventListener("pos_event", e=>{
  try{ evPrepend(JSON.parse(e.data)); }catch(_){}
});
</script>
</body></html>
"""
    return HTMLResponse(html)
