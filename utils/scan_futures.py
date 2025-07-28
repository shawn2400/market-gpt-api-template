from aiohttp import web
import aiohttp
import numpy as np

async def fetch_binance_futures_data():
    url = 'https://fapi.binance.com/fapi/v1/ticker/24hr'
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            raw_data = await resp.json()

    top_20 = sorted(raw_data, key=lambda x: float(x['quoteVolume']), reverse=True)[:20]

    results = []
    for item in top_20:
        symbol = item['symbol']
        last_price = float(item['lastPrice'])
        volume = float(item['quoteVolume'])

        # חישוב מדומה של RSI ו-ADX (אפשר להחליף בחישוב אמיתי)
        rsi = np.random.uniform(20, 80)
        adx = np.random.uniform(10, 50)
        direction = "LONG" if rsi < 30 else "SHORT" if rsi > 70 else "NEUTRAL"

        results.append({
            'symbol': symbol,
            'last_price': last_price,
            'volume': volume,
            'rsi': round(rsi, 2),
            'adx': round(adx, 2),
            'direction': direction
        })

    return results

async def scan_futures_market(request):
    try:
        data = await fetch_binance_futures_data()
        return web.json_response({'results': data})
    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)

# הגדרה להפעלה כשרת עצמאי
if __name__ == '__main__':
    app = web.Application()
    app.router.add_get('/scan_futures_market', scan_futures_market)
    web.run_app(app, port=8080)

