# utils/semaphore_manager.py

import asyncio

# ✅ מגביל ל־5 קריאות async במקביל – מונע עומס על Binance/API
semaphore = asyncio.Semaphore(5)
