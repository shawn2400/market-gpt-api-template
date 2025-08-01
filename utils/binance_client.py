# utils/binance_client.py

import os
import sys
import logging
from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException

# Configure logging to support UTF-8 output if possible
handler = logging.StreamHandler(stream=sys.stdout)
try:
    handler.set_encoding('utf-8')
except Exception:
    pass  # if not supported, continue
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(message)s',
    handlers=[handler]
)

# Retrieve API credentials from environment (Render secrets or direct env vars)
API_KEY = os.getenv('BINANCE_API_KEY')
API_SECRET = os.getenv('BINANCE_API_SECRET')

# Global Binance client instance
client: Client | None = None

def init_binance_client() -> None:
    """
    Initialize Binance API client for Spot and Futures.
    Raises EnvironmentError if credentials are missing.
    """
    global client
    try:
        if not API_KEY or not API_SECRET:
            raise EnvironmentError(
                'Environment variables BINANCE_API_KEY and BINANCE_API_SECRET are required.'
            )

        # Initialize client (defaults to https://api.binance.com)
        client = Client(API_KEY, API_SECRET)

        # Verify connectivity
        client.ping()
        client.futures_account()  # checks futures endpoint

        logging.info('Binance client connected successfully.')

    except (BinanceAPIException, BinanceRequestException) as e:
        logging.error(f'[Binance API Error] {e}')
        client = None
    except Exception as e:
        logging.error(f'[Binance Init Error] {e}')
        client = None

# Automatically initialize on import
init_binance_client()




















