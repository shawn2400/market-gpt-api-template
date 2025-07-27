import os
from binance.client import Client
from dotenv import load_dotenv

# טוען משתני סביבה מקובץ .env
load_dotenv()

# יצירת לקוח Binance על בסיס מפתחות סודיים מה־env
client = Client(
    api_key=os.getenv("BINANCE_API_KEY"),
    api_secret=os.getenv("BINANCE_API_SECRET")
)
