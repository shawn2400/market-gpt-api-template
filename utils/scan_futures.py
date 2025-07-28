import asyncio
from aiohttp import web, ClientSession
import numpy as np
import os
import logging

logging.basicConfig(level=logging.INFO)

async def fetch_binance_futures_data(limit: int = 30):
    url = 'https://fapi.binance.com/fapi/v1/ticker/24hr'
    async with ClientSession() as session:
        async with session.get(url, timeout=10) as resp:
            if resp.status != 200:
                raise Exception(f"Binance API returned status {resp.status}")
            raw_data = await resp.json()

    # מיון לפי נפח מסחר (quoteVolume)
    top_symbols = sorted(raw_data, key=lambda x: float(x['quoteVolume']), reverse=True)[:limit]

    results = []
    for item in top_symbols:
        try:
            symbol = item['symbol']
            last_price = float(item['lastPrice'])
            volume = float(item['quoteVolume'])

            # סימולציה זמנית של RSI ו־ADX
            rsi = np.random.uniform(20, 80)
            adx = np.random.uniform(10, 50)
            direction = "LONG" if rsi < 30 else "SHORT" if rsi > 70 else "NEUTRAL"

            results.append({
                'symbol': symbol,
                'last_price': round(last_price, 6),
                'volume': round(volume, 2),
                'rsi': round(rsi, 2),
                'adx': round(adx, 2),
                'direction': direction
            })
        except Exception as e:
            logging.warning(f"[!] שגיאה בעיבוד {item.get('symbol', '')}: {e}")
            continue

    return results

async def scan_futures_market(request):
    try:
        data = await fetch_binance_futures_data(limit=30)
        return web.json_response({'results': data})
    except Exception as e:
        logging.error(f"[!] שגיאה ב־scan_futures_market: {e}")
        return web.json_response({'error': str(e)}, status=500)

def create_app():
    app = web.Application()
    app.router.add_get('/scan_futures_market', scan_futures_market)
    return app

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    logging.info(f"🚀 Starting server on port {port}")
    web.run_app(create_app(), port=port)






