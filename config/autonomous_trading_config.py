#!/usr/bin/env python3
# config/autonomous_trading_config.py
"""
🚀 Autonomous Trading Configuration
Full autonomous mode with aggressive risk profile
NO human approval required - AI decides everything
"""
import os

# ==========================================
# 🤖 AUTONOMOUS OPERATION MODE
# ==========================================
AUTONOMOUS_CONFIG = {
    "approval_required": False,  # ❌ NO Telegram approval
    "auto_execute": True,         # ✅ YES automatic execution
    "ai_management": True,        # ✅ YES AI manages positions  
    "human_override_only": True,  # ✅ YES human only for emergency stop
}

# Set environment variables for backward compatibility
os.environ.setdefault("APPROVAL_ENABLED", "0")
os.environ.setdefault("REQUIRE_TELEGRAM_APPROVAL", "0")
os.environ.setdefault("AUTO_OPEN_ON_APPROVE", "1")
os.environ.setdefault("EXECUTE_TRADES", "1")

# ==========================================
# 🛡️ RISK PROFILE: AGGRESSIVE
# ==========================================
RISK_PROFILE = {
    # Stop Loss & Take Profit
    "min_stop_loss_pct": 1.0,        # 1.0% minimum SL (was 1.5%)
    "max_stop_loss_pct": 5.0,        # 5.0% maximum SL
    "min_take_profit_pct": 2.0,      # 2.0% minimum TP (was 2.5%)
    "max_take_profit_pct": 15.0,     # 15.0% maximum TP
    "min_rr_ratio": 1.5,             # 1.5:1 minimum R:R (was 2.0)
    
    # Position Sizing
    "position_size_pct": 3.5,        # 3.5% of equity per trade (was 2%)
    "min_position_size_pct": 3.0,    # 3.0% minimum
    "max_position_size_pct": 5.0,    # 5.0% maximum
    
    # Leverage
    "min_leverage": 3,               # 3x minimum (was 5x)
    "max_leverage": 15,              # 15x maximum (was 12x)
    "default_leverage": 7,           # 7x default
    
    # Trade Frequency
    "max_daily_trades": 6,           # 4-6 quality trades/day (was 10+)
    "min_holding_time_minutes": 5,   # 5 min minimum (prevent scalping)
    "cooldown_after_loss_minutes": 30,  # 30 min cooldown after loss
    
    # Quality Filters
    "min_quality_score": 6.0,        # 6/10 minimum quality (Smart Filter)
    "min_ai_consensus": 2,           # 2/3 brains required
    "min_market_cap_rank": 200,      # Top 200 coins only
}

# Set environment variables
os.environ.setdefault("MIN_SL_PCT", str(RISK_PROFILE["min_stop_loss_pct"]))
os.environ.setdefault("MAX_SL_PCT", str(RISK_PROFILE["max_stop_loss_pct"]))
os.environ.setdefault("MIN_TP_PCT", str(RISK_PROFILE["min_take_profit_pct"]))
os.environ.setdefault("MIN_RR", str(RISK_PROFILE["min_rr_ratio"]))
os.environ.setdefault("POSITION_SIZE_PCT", str(RISK_PROFILE["position_size_pct"]))
os.environ.setdefault("MAX_LEVERAGE", str(RISK_PROFILE["max_leverage"]))
os.environ.setdefault("MAX_DAILY_TRADES", str(RISK_PROFILE["max_daily_trades"]))

# ==========================================
# 🧠 AI CONFIGURATION (Cost-Optimized)
# ==========================================
AI_CONFIG = {
    # 3 Brains (95% cost reduction)
    "brains": ["DeepSeek", "Grok", "GPT-4o-mini"],
    "consensus_threshold": 2,  # 2/3 majority
    
    # Cost Limits (Daily)
    "max_daily_cost_usd": 5.0,  # $5/day maximum
    "alert_threshold_usd": 3.0,  # Alert at $3
    
    # Smart Filter
    "enable_smart_filter": True,
    "volume_spike_min": 1.5,  # 150% of average
    "price_change_min": 2.0,  # 2% move
    "quality_score_min": 6.0,  # 6/10 minimum
}

os.environ.setdefault("ENABLE_SMART_FILTER", "1")
os.environ.setdefault("QUALITY_SCORE_MIN", str(AI_CONFIG["quality_score_min"]))

# ==========================================
# 📊 PERFORMANCE TARGETS
# ==========================================
PERFORMANCE_TARGETS = {
    "win_rate_target": 60.0,         # 60% win rate target
    "avg_rr_target": 2.0,            # 2.0 R:R average
    "max_drawdown_pct": 15.0,        # 15% maximum drawdown
    "daily_pnl_target_pct": 2.0,     # 2% daily target
    "monthly_pnl_target_pct": 25.0,  # 25% monthly target
}

# ==========================================
# ⚡ SCANNER CONFIGURATION
# ==========================================
SCANNER_CONFIG = {
    "interval_seconds": 300,  # 5 minutes (was 120s)
    "symbols_per_cycle": 8,   # 8 symbols per scan
    "max_concurrent": 2,      # 2 concurrent AI calls
}

os.environ.setdefault("SUGGEST_INTERVAL_SEC", str(SCANNER_CONFIG["interval_seconds"]))
os.environ.setdefault("SYMBOLS_PER_CYCLE", str(SCANNER_CONFIG["symbols_per_cycle"]))

# ==========================================
# 📱 NOTIFICATION CONFIG
# ==========================================
NOTIFICATION_CONFIG = {
    "telegram_enabled": True,
    "send_on_entry": True,
    "send_on_exit": True,
    "send_ai_consensus": True,  # NEW: Send AI consensus reasoning
    "send_daily_report": True,
    "language_mix": "70% Hebrew + 30% English",
}

os.environ.setdefault("TELEGRAM_SEND_ENABLE", "1")

print("✅ Autonomous Trading Config loaded:")
print(f"   - Mode: FULL AUTONOMOUS (no approvals)")
print(f"   - Risk: AGGRESSIVE (SL={RISK_PROFILE['min_stop_loss_pct']}%, TP={RISK_PROFILE['min_take_profit_pct']}%)")
print(f"   - AI: 3 Brains (DeepSeek + Grok + GPT-4o-mini)")
print(f"   - Scanner: {SCANNER_CONFIG['interval_seconds']}s interval")
print(f"   - Max Daily Trades: {RISK_PROFILE['max_daily_trades']}")
