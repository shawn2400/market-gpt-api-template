# utils/ws_fallback.py
import httpx

async def get_price(symbol: str) -> float:
    s = symbol.upper()
    # נסה Mark Price, אם לא – Ticker
    async with httpx.AsyncClient(timeout=8) as x:
        r = await x.get("https://fapi.binance.com/fapi/v1/premiumIndex", params={"symbol": s})
        if r.status_code == 200:
            data = r.json()
            p = float(data.get("markPrice", 0))
            if p > 0:
                return p
        r2 = await x.get("https://fapi.binance.com/fapi/v1/ticker/price", params={"symbol": s})
        r2.raise_for_status()
        return float(r2.json().get("price"))















