# utils/binance_client.py
import os
from binance.client import Client
from dotenv import load_dotenv

load_dotenv()

client = Client(
    api_key=os.getenv("BINANCE_API_KEY"),
    api_secret=os.getenv("BINANCE_API_SECRET")
)
