import asyncio
import httpx

FAPI = "https://fapi.binance.com"

async def get_price(symbol: str) -> float:
    sym = symbol.upper()
    url = f"{FAPI}/fapi/v1/premiumIndex"
    params = {"symbol": sym}
    for i in range(3):
        try:
            async with httpx.AsyncClient(timeout=6.0) as x:
                r = await x.get(url, params=params)
            r.raise_for_status()
            j = r.json()
            price = float(j.get("markPrice") or j.get("lastFundingRate") or 0.0)
            if price and price > 0:
                return price
        except Exception:
            await asyncio.sleep(0.5 * (i + 1))
    raise RuntimeError(f"failed to fetch price for {sym}")















