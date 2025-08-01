# utils/binance_client.py
import os
import logging
from dotenv import load_dotenv
from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(message)s'
)

# Retrieve API credentials
API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")

# Global Binance client instance
client: Client | None = None


def init_binance_client() -> None:
    """
    Initialize the Binance API client for both Spot and Futures.
    Raises EnvironmentError if API_KEY or API_SECRET are missing.
    """
    global client
    try:
        if not API_KEY or not API_SECRET:
            raise EnvironmentError(
                "❌ BINANCE_API_KEY and BINANCE_API_SECRET must be set in environment"
            )

        # Initialize the client; defaults to https://api.binance.com
        client = Client(API_KEY, API_SECRET)

        # Test connectivity endpoints
        client.ping()
        client.futures_account()  # ensures futures endpoints work

        logging.info("✅ Binance client connected (Spot + Futures)")

    except (BinanceAPIException, BinanceRequestException) as e:
        logging.error(f"[Binance API Error] {e}")
        client = None
    except Exception as e:
        logging.error(f"[Binance Init Error] {e}")
        client = None


# Automatically initialize on import
init_binance_client()
















