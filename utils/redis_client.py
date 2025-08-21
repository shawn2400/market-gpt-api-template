# utils/redis_client.py
import os, logging, redis
from dotenv import load_dotenv

load_dotenv(override=True)
logger = logging.getLogger("algogpt.redis")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
redis_client: redis.Redis | None = None

try:
    redis_client = redis.Redis.from_url(
        REDIS_URL,
        decode_responses=True,        # string במקום bytes
        socket_connect_timeout=5,     # fail fast אם אין חיבור
        health_check_interval=30,     # שומר חיבור בריא
    )
    redis_client.ping()
    logger.info(f"[Redis] ✅ Connected to {REDIS_URL}")
except Exception as e:
    redis_client = None
    logger.error(f"[Redis] ❌ Connection failed: {e}")



