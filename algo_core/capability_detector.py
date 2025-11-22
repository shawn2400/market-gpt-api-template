"""
Capability Detector — Auto-detect Free/Paid Plans
"""
import os
import logging

logger = logging.getLogger("CapabilityDetector")

def detect_capabilities(bot_name: str, cfg: dict) -> dict:
    """
    Auto-detect if bot is Free or Paid plan
    Check environment variables: PAID_{BOT_NAME}
    """
    env_key = f"PAID_{bot_name.upper()}"
    
    if os.getenv(env_key):
        logger.info(f"🟢 {bot_name}: PAID plan detected")
        return cfg.get("paid_capabilities", cfg.get("free_capabilities"))
    else:
        logger.info(f"🟡 {bot_name}: FREE plan (use PAID_{env_key}=1 to upgrade)")
        return cfg.get("free_capabilities", {})

def is_paid(bot_name: str) -> bool:
    """Check if bot is on paid plan"""
    env_key = f"PAID_{bot_name.upper()}"
    return bool(os.getenv(env_key))

def upgrade_plan(bot_name: str):
    """Upgrade bot to paid plan"""
    env_key = f"PAID_{bot_name.upper()}"
    os.environ[env_key] = "1"
    logger.info(f"⬆️ Upgraded {bot_name} to PAID")

def downgrade_plan(bot_name: str):
    """Downgrade bot to free plan"""
    env_key = f"PAID_{bot_name.upper()}"
    if env_key in os.environ:
        del os.environ[env_key]
    logger.info(f"⬇️ Downgraded {bot_name} to FREE")
