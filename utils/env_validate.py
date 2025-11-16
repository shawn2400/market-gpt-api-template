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
    
    # Check AI providers (core providers only - Gemini/DeepSeek are optional)
    ai_providers = {
        "OpenAI (GPT-5)": "OPENAI_API_KEY",
        "Anthropic (Claude)": "ANTHROPIC_API_KEY",
        "XAI (Grok)": "XAI_API_KEY",
    }
    
    # Optional AI providers (won't trigger warnings)
    optional_providers = {
        "Gemini": "GEMINI_API_KEY",
        "DeepSeek": "DEEPSEEK_API_KEY",
    }
    
    ai_active = []
    optional_active = []
    
    for name, key in ai_providers.items():
        if os.getenv(key):
            ai_active.append(name)
    
    for name, key in optional_providers.items():
        if os.getenv(key):
            optional_active.append(name)
    
    all_active = ai_active + optional_active
    if all_active:
        logger.info(f"✅ AI Providers active ({len(all_active)}): {', '.join(all_active)}")
    
    # Check GitHub auto-commit (optional feature)
    github_token = os.getenv("GITHUB_TOKEN")
    github_repo = os.getenv("GITHUB_REPO")
    
    if github_token and github_repo:
        logger.info("✅ GitHub auto-commit enabled")
    else:
        logger.info("ℹ️  GitHub auto-commit disabled (optional feature)")
    
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
