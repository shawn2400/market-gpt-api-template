import os
import logging
from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] [%(levelname)s] %(message)s', force=True)

BINANCE_API_KEY=TS2IvqKnUfv370onkdq9MvA7DYFF8gATAWetiSxWVmXC5crw71jf2HJ9DknWK9HW
BINANCE_API_SECRET=FzmwOV59i3qoIgJ2862eJlQ9tHeq94SdZ9uvL5vrlP1trml0WwRlSm2RVBJb7Ki0


client = None

def init_binance_client():
    global client
    try:
        if not API_KEY or not API_SECRET:
            raise EnvironmentError("❌ BINANCE_API_KEY or BINANCE_API_SECRET not set")

        client = Client(API_KEY, API_SECRET)

        # ✅ פתרון עוקף – במידה וה־default URL מחזיר HTML
        client.API_URL = "https://api1.binance.com/api"

        client.ping()
        client.futures_account()
        logging.info("✅ Binance client connected (Spot + Futures)")

    except (BinanceAPIException, BinanceRequestException) as e:
        logging.error(f"[Binance API Error] {e}")
        client = None
    except Exception as e:
        logging.error(f"[Binance Init Error] {e}")
        client = None

init_binance_client()























