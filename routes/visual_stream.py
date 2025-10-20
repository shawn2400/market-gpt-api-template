# routes/visual_stream.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import asyncio, json
from typing import Optional
from fastapi import APIRouter, Header, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, StreamingResponse

from utils.redis_helper import get_redis

router = APIRouter(prefix="/public", tags=["Public Feed"])

async def _sse_event(event: str, data: dict) -> bytes:
    payload = f"event: {event}\n" + "data: " + json.dumps(data, ensure_ascii=False, separators=(",",":")) + "\n\n"
    return payload.encode("utf-8")

@router.get("/sse-positions")
async def sse_positions(request: Request):
    """
    זרם SSE “positions” + “pos:<SYMBOL>” (אם תרצה לפצל בצד לקוח).
    קורא כל ~2 שניות את pos:all מ-Redis.
    """
    r = await get_redis()
    if not r:
        return PlainTextResponse("redis_unavailable", status_code=503)

    async def gen():
        while True:
            if await request.is_disconnected():
                break
            try:
                raw = await r.get("pos:all")
                if raw:
                    doc = json.loads(raw)
                    yield await _sse_event("positions", doc)
            except Exception:
                pass
            await asyncio.sleep(2)
    headers = {
        "Cache-Control": "no-cache",
        "Content-Type": "text/event-stream",
        "Connection": "keep-alive",
    }
    return StreamingResponse(gen(), headers=headers)

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
</style>
</head><body>
<div class="wrap">
  <h2>Positions <small>live</small></h2>
  <div id="ts"><small>–</small></div>
  <div id="grid" class="grid"></div>
</div>
<script>
const grid = document.getElementById("grid");
const ts = document.getElementById("ts");
function fmt(x,d=4){if(x==null)return "-"; try{return Number(x).toFixed(d)}catch{return x}}
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
function render(items){
  grid.innerHTML = items.map(card).join("");
}
const ev = new EventSource("/public/sse-positions");
ev.addEventListener("positions", e=>{
  try{
    const d = JSON.parse(e.data);
    ts.innerHTML = `<small>ts: ${new Date((d.ts||0)*1000).toISOString().replace('T',' ').slice(0,19)}</small>`;
    render(d.items||[]);
  }catch(_){}
});
</script>
</body></html>
"""
    return HTMLResponse(html)
