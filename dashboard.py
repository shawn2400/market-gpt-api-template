# routes/dashboard.py
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()

@router.get("/dashboard", response_class=HTMLResponse, operation_id="getDashboardHtml")
async def dashboard_ui():
    return """
    <!doctype html>
    <html lang="he" dir="rtl">
      <head>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width,initial-scale=1" />
        <title>AlgoGPT Dashboard</title>
        <style>
          body { font-family: system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif; margin:40px; }
          .card { border:1px solid #ddd; border-radius:12px; padding:16px; margin-bottom:16px; }
          .row { display:flex; gap:12px; flex-wrap:wrap; align-items:center; }
          input,select,button { padding:8px 10px; border-radius:8px; border:1px solid #ccc; }
          button { cursor:pointer; }
          code { background:#f6f8fa; padding:2px 6px; border-radius:6px; }
          .ok { color:#1a7f37; }
          .err { color:#b42318; }
          pre { background:#0b1020; color:#d6e5ff; padding:12px; border-radius:10px; overflow:auto; }
        </style>
      </head>
      <body>
        <h1>📊 AlgoGPT Dashboard</h1>

        <div class="card">
          <h3>AI Health</h3>
          <button onclick="probeAi()">בדוק</button>
          <div id="aiHealth"></div>
        </div>

        <div class="card">
          <h3>SL/TP הצעה</h3>
          <div class="row">
            <input id="sltp_symbol" placeholder="BTCUSDT" value="BTCUSDT" />
            <select id="sltp_dir"><option>LONG</option><option>SHORT</option></select>
            <input id="sltp_entry" type="number" step="0.01" placeholder="Entry" />
            <input id="sltp_atr" type="number" step="0.01" placeholder="ATR (אופציונלי)" />
            <button onclick="askSLTP()">חשב</button>
          </div>
          <pre id="sltp_out" hidden></pre>
        </div>

        <div class="card">
          <h3>Backtest</h3>
          <div class="row">
            <input id="bt_symbol" placeholder="BTCUSDT" value="BTCUSDT" />
            <select id="bt_tf">
              <option>5m</option><option selected>15m</option><option>1h</option><option>4h</option>
            </select>
            <input id="bt_limit" type="number" value="200" />
            <button onclick="runBT()">הרץ</button>
          </div>
          <pre id="bt_out" hidden></pre>
        </div>

        <script>
          async function probeAi(){
            const r = await fetch('/ai/health');
            const j = await r.json();
            document.getElementById('aiHealth').innerHTML =
              j.ok ? '<span class="ok">OK</span> — ' + (j.model||'') :
                     '<span class="err">Error</span>: ' + (j.error||'unknown');
          }
          async function askSLTP(){
            const symbol = document.getElementById('sltp_symbol').value.trim();
            const direction = document.getElementById('sltp_dir').value;
            const entry = parseFloat(document.getElementById('sltp_entry').value);
            const atrRaw = document.getElementById('sltp_atr').value.trim();
            const body = { symbol, direction, entry };
            if(atrRaw) body.atr = parseFloat(atrRaw);
            const r = await fetch('/trade/sltp', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
            const j = await r.json();
            const pre = document.getElementById('sltp_out');
            pre.hidden = false; pre.textContent = JSON.stringify(j, null, 2);
          }
          async function runBT(){
            const symbol = document.getElementById('bt_symbol').value.trim();
            const timeframe = document.getElementById('bt_tf').value;
            const limit = parseInt(document.getElementById('bt_limit').value,10);
            const r = await fetch('/backtest', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({symbol,timeframe,limit})});
            const j = await r.json();
            const pre = document.getElementById('bt_out');
            pre.hidden = false; pre.textContent = JSON.stringify(j, null, 2);
          }
        </script>
      </body>
    </html>
    """


