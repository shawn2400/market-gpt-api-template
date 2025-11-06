# -*- coding: utf-8 -*-
"""
Environment Variables Validation Module
Fail-fast on missing critical API keys and configuration
"""
from __future__ import annotations
import os
import sys
import logging

logger = logging.getLogger(__name__)

# Soft requirements (warning only)
REQUIRED_SOFT = [
    "OPENAI_API_KEY",
    "GITHUB_REPO",
]

# Hard requirements (exit if missing)
REQUIRED_HARD = []  # Add here if you want to force exit on missing vars


def validate_env(strict: bool = False) -> None:
    """
    Validate environment variables
    
    Args:
        strict: If True, exits on any missing soft requirements
    """
    missing_soft = [k for k in REQUIRED_SOFT if not os.getenv(k)]
    missing_hard = [k for k in REQUIRED_HARD if not os.getenv(k)]
    
    if missing_soft:
        logger.warning(f"Missing (soft) ENV vars: {', '.join(missing_soft)}")
        logger.warning("Some features may be disabled or degraded")
        
        if strict:
            logger.error("Strict mode enabled - exiting due to missing soft requirements")
            sys.exit(1)
    
    if missing_hard:
        logger.error(f"Missing (hard) ENV vars: {', '.join(missing_hard)}")
        logger.error("Cannot start without these critical variables")
        sys.exit(1)
    
    # Check Neon credentials
    neon_vars = ["NEON_API_KEY", "NEON_PROJECT_ID", "NEON_ENDPOINT_ID"]
    neon_missing = [k for k in neon_vars if not os.getenv(k)]
    
    if neon_missing:
        logger.warning(f"Neon auto-resume disabled - missing: {', '.join(neon_missing)}")
    else:
        logger.info("✅ Neon auto-resume credentials present")
    
    # Check AI providers
    ai_providers = {
        "OpenAI (GPT-5)": "OPENAI_API_KEY",
        "Anthropic (Claude)": "ANTHROPIC_API_KEY",
        "Gemini": "GEMINI_API_KEY",
        "DeepSeek": "DEEPSEEK_API_KEY",
        "XAI (Grok)": "XAI_API_KEY",
    }
    
    ai_active = []
    ai_missing = []
    
    for name, key in ai_providers.items():
        if os.getenv(key):
            ai_active.append(name)
        else:
            ai_missing.append(name)
    
    if ai_active:
        logger.info(f"✅ AI Providers active ({len(ai_active)}/5): {', '.join(ai_active)}")
    
    if ai_missing:
        logger.warning(f"⚠️ AI Providers missing ({len(ai_missing)}/5): {', '.join(ai_missing)}")
        logger.warning("Post-Trade AI Review will use fewer brains")
    
    # Check GitHub auto-commit
    github_vars = ["GITHUB_TOKEN", "GITHUB_REPO"]
    github_missing = [k for k in github_vars if not os.getenv(k)]
    
    if github_missing:
        logger.warning(f"GitHub auto-commit disabled - missing: {', '.join(github_missing)}")
    else:
        logger.info("✅ GitHub auto-commit credentials present")
    
    # Check Binance
    binance_vars = ["BINANCE_API_KEY", "BINANCE_API_SECRET"]
    binance_missing = [k for k in binance_vars if not os.getenv(k)]
    
    if binance_missing:
        logger.error(f"❌ Binance credentials missing: {', '.join(binance_missing)}")
        logger.error("Trading will not work without Binance credentials")
        if strict:
            sys.exit(1)
    else:
        logger.info("✅ Binance credentials present")
    
    logger.info("Environment validation complete")
