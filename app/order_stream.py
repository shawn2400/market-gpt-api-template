# /app/app/order_stream.py
from __future__ import annotations
import os, asyncio, logging

log = logging.getLogger("order_stream")

# ננסה קודם את ws_user_stream (יש אצלך), ואם לא – את user_stream (יש גם)
try:
    from utils.ws_user_stream import start as ws_start
except Exception:
    ws_start = None

try:
    from utils.user_stream import start_user_stream_consumer as legacy_start
except Exception:
    legacy_start = None

async def _run():
    if os.getenv("USER_STREAM_ENABLE", "0").strip().lower() not in ("1", "true", "yes", "on"):
        log.info("user-stream disabled by env")
        return
    if ws_start:
        try:
            ws_start()
            log.info("user-stream started via utils.ws_user_stream")
        except Exception as e:
            log.warning("ws_user_stream.start failed: %s", e)
    elif legacy_start:
        try:
            await legacy_start()
            log.info("user-stream started via utils.user_stream")
        except Exception as e:
            log.warning("legacy user_stream.start failed: %s", e)
    else:
        log.warning("no user-stream implementation found")

if __name__ == "__main__":
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        pass


