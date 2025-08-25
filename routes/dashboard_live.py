# dashboard_live.py
from __future__ import annotations
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from fastapi.responses import HTMLResponse
from utils.auth import require_api_key
from utils.get_klines import get_klines
from utils.indicators import prepare_indicators_for_backtest
from utils.ai_analysis import analyze_with_ai
from utils.quality import compute_quality
import asyncio, json, os, time

router = APIRouter(
    prefix="/dashboard",
    tags=["Dashboard"],
    dependencies=[Depends(require_api_key)],
)

# רשימת WebSocket Live לכל המשתמשים
clients: list[WebSocket] = []

async def _analyze_symbol(symbol: str, interval: str = "15m") -> dict:
    """
    ניתוח מלא לסימבול כולל אינדיקטורים, GPT, Quality Score.
    """
    try:
        df = await get_klines(symbol, interval=interval, limit=200, market="futures")
        indicators = prepare_indicators_for_backtest(df)
        row = indicators.iloc[-1].to_dict()

        # קריאת GPT
        ai_text = await analyze_with_ai({"symbol": symbol, **row})

        # Quality Score לפי כללים מתקדמים
        q = compute_quality(
            symbol=symbol,
            side="LONG" if row.get("ema_21", 0) < row.get("close", 0) else "SHORT",
            entry=float(row.get("close", 0)),
            sl=None, tp=None,
            leverage=10,
            budget=50,
            anchor=None,
            atr=row.get("atr", None)
        )

        return {
            "symbol": symbol,
            "interval": interval,
            "price": float(row.get("close", 0)),
            "rsi": round(row.get("rsi", 0), 2),
            "adx": round(row.get("adx", 0), 2),
            "ema_21": round(row.get("ema_21", 0), 2),
            "atr": round(row.get("atr", 0), 4),
            "volume": round(row.get("volume", 0), 2),
            "trend": "UP" if row.get("ema_21", 0) < row.get("close", 0) else "DOWN",
            "ai_analysis": ai_text,
            "quality_score": q.get("quality_score", 0),
            "success_pct": q.get("success_pct", 0),
        }
    except Exception as e:
        return {"symbol": symbol, "error": str(e)}

async def broadcast_update(data: dict):
    """
    שולח עדכון חי לכל הלקוחות המחוברים.
    """
    dead_clients = []
    for ws in clients:
        try:
            await ws.send_json(data)
        except WebSocketDisconnect:
            dead_clients.append(ws)
    for dead in dead_clients:
        clients.remove(dead)

@router.websocket("/live")
async def websocket_dashboard(websocket: WebSocket):
    """
    WebSocket שמזרים את כל המידע בזמן אמת.
    """
    await websocket.accept()
    clients.append(websocket)

    try:
        while True:
            # טעינת watchlist.json כדי לעדכן סמלים בזמן אמת
            from utils.watchlist_utils import load_watchlist
            watchlist = [it["symbol"] for it in load_watchlist()]
            if "BTCUSDT" not in watchlist:
                watchlist.insert(0, "BTCUSDT")

            updates = []
            for sym in watchlist:
                result = await _analyze_symbol(sym)
                updates.append(result)

                # שולחים עדכון פר סימבול
                await broadcast_update(result)

                # מגבלת עומסים
                await asyncio.sleep(0.5)

            # שליחה כוללת לכל המחוברים
            await broadcast_update({"type": "batch", "results": updates})

            # רענון כל 60 שניות
            await asyncio.sleep(60)

    except WebSocketDisconnect:
        clients.remove(websocket)

# דף HTML מובנה לניהול בזמן אמת
@router.get("/", response_class=HTMLResponse)
async def dashboard_page():
    """
    ממשק חזותי בזמן אמת — ניתן לפתוח בדפדפן.
    """
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>AlgoGPT Live Dashboard</title>
        <meta charset="UTF-8">
        <style>
            body { background: #111; color: #eee; font-family: monospace; padding: 10px; }
            .symbol { border-bottom: 1px solid #333; padding: 6px; }
            .green { color: #0f0; }
            .red { color: #f00; }
        </style>
    </head>
    <body>
        <h2>🚀 AlgoGPT Live Dashboard</h2>
        <div id="content">מתחבר לשרת...</div>
        <script>
            const ws = new WebSocket(`ws://${location.host}/dashboard/live`);
            ws.onmessage = (ev) => {
                const data = JSON.parse(ev.data);
                if (data.symbol) {
                    const elem = document.createElement("div");
                    elem.className = "symbol";
                    elem.innerHTML = `<b>${data.symbol}</b> | מחיר: ${data.price} | RSI: ${data.rsi} | ADX: ${data.adx} | ציון: ${data.quality_score.toFixed(2)} | ${data.ai_analysis}`;
                    document.getElementById("content").prepend(elem);
                }
            };
            ws.onclose = () => {
                document.getElementById("content").innerText = "❌ נותק מהשרת";
            };
        </script>
    </body>
    </html>
    """
