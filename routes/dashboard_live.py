# routes/dashboard_live.py
from __future__ import annotations
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from fastapi.responses import HTMLResponse
from utils.auth import require_api_key
from utils.get_klines import get_klines
from utils.indicators import prepare_indicators_for_backtest
from utils.ai_analysis import analyze_with_ai
from utils.quality import compute_quality
import asyncio, json, logging

logger = logging.getLogger("algogpt.dashboard")

router = APIRouter(
    prefix="/dashboard",
    tags=["Dashboard"],
    dependencies=[Depends(require_api_key)],
)

clients: list[WebSocket] = []

async def _analyze_symbol(symbol: str, interval: str = "15m") -> dict:
    """ ניתוח מלא לסימבול כולל אינדיקטורים, GPT, Quality Score. """
    try:
        df = await get_klines(symbol, interval=interval, limit=200, market="futures")
        if df is None or df.empty:
            return {"symbol": symbol, "ok": False, "error": "no data"}

        indicators = prepare_indicators_for_backtest(df)
        row = indicators.iloc[-1].to_dict()

        ai_text = ""
        try:
            ai_text = await analyze_with_ai({"symbol": symbol, **row})
        except Exception as e:
            logger.warning("ai_analysis failed for %s: %s", symbol, e)

        q = {}
        try:
            q = compute_quality(
                symbol=symbol,
                side="LONG" if row.get("ema_21", 0) < row.get("close", 0) else "SHORT",
                entry=float(row.get("close", 0)),
                sl=None, tp=None,
                leverage=10,
                budget=50,
                anchor=None,
                atr=row.get("atr", None),
            )
        except Exception as e:
            logger.warning("quality_score failed for %s: %s", symbol, e)
            q = {"quality_score": 0, "success_pct": 0}

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
            "ok": True,
        }
    except Exception as e:
        logger.error("dashboard analyze failed: %s", e)
        return {"symbol": symbol, "ok": False, "error": str(e)}

async def broadcast_update(data: dict):
    dead_clients = []
    for ws in clients:
        try:
            await ws.send_json(data)
        except Exception:
            dead_clients.append(ws)
    for dead in dead_clients:
        try:
            clients.remove(dead)
        except Exception:
            pass

@router.websocket("/live")
async def websocket_dashboard(websocket: WebSocket):
    await websocket.accept()
    clients.append(websocket)
    logger.info("📡 client connected to dashboard")

    try:
        while True:
            from utils.watchlist_utils import load_watchlist
            try:
                watchlist = [it["symbol"] for it in load_watchlist()]
            except Exception:
                watchlist = []
            if "BTCUSDT" not in watchlist:
                watchlist.insert(0, "BTCUSDT")

            updates = []
            for sym in watchlist:
                result = await _analyze_symbol(sym)
                updates.append(result)
                await broadcast_update(result)
                await asyncio.sleep(0.5)

            await broadcast_update({"ok": True, "type": "batch", "results": updates})
            await asyncio.sleep(60)

    except WebSocketDisconnect:
        logger.info("❌ client disconnected from dashboard")
        if websocket in clients:
            clients.remove(websocket)
    except Exception as e:
        logger.error("dashboard websocket error: %s", e)
        if websocket in clients:
            clients.remove(websocket)

@router.get("/", response_class=HTMLResponse)
async def dashboard_page():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>AlgoGPT Live Dashboard</title>
        <meta charset="UTF-8">
        <style>
            body { background: #111; color: #eee; font-family: monospace; padding: 10px; }
            .symbol { border-bottom: 1px solid #333; padding: 6px; }
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
                    elem.innerHTML = `<b>${data.symbol}</b> | מחיר: ${data.price} | RSI: ${data.rsi} | ADX: ${data.adx} | ציון: ${data.quality_score}`;
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


