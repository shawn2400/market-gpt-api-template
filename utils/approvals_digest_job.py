# utils/approvals_digest_job.py
import asyncio, logging
log = logging.getLogger("algogpt.approvals.digest_job")

_task = None

async def digest_loop():
    while True:
        try:
            # ... הלוגיקה שלך כאן ...
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            break
        except Exception as e:
            log.warning({"event":"digest_loop_err","err":str(e)})
            await asyncio.sleep(5)

def start_expired_digest_job():
    global _task
    if _task and not _task.done():
        return _task
    _task = asyncio.create_task(digest_loop(), name="expired_digest_job")
    return _task
