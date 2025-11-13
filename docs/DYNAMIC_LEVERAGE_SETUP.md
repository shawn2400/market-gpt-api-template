# Hybrid Dynamic Leverage v2.0 - Setup Guide

## 🚀 Quick Start

To enable the Dynamic Leverage system, add this to your Render Environment Variables:

```bash
DYNAMIC_LEVERAGE_MODE=1
```

That's it! The system will use intelligent defaults. For advanced customization, see below.

---

## 📋 Core Configuration

### **Enable/Disable**
```bash
DYNAMIC_LEVERAGE_MODE=1              # 1=enabled, 0=disabled (falls back to static)
DYNAMIC_MIN_LEVERAGE=2               # Absolute minimum leverage
DYNAMIC_MAX_LEVERAGE=35              # Absolute maximum leverage
```

---

## 🛡️ Safety Guards Configuration

### **Emergency Brake**
Activates when performance is poor:

```bash
EMERGENCY_WIN_RATE=0.30              # Win rate threshold (30% = emergency)
EMERGENCY_CONSEC_LOSSES=3            # Consecutive losses trigger (3 losses = emergency)
EMERGENCY_DAILY_LOSS=200.0           # Daily loss limit ($200 = stop trading)
```

**Example:** If win rate drops below 30%, max leverage = 5x

---

### **Volatility Guard**
Protects against extreme market conditions:

```bash
VOLATILITY_EXTREME_ATR=0.05          # Extreme volatility threshold (5%)
VOLATILITY_HIGH_ATR=0.03             # High volatility threshold (3%)
```

**Example:** If ATR > 5%, max leverage = 10x

---

### **Portfolio Protection**
Limits total exposure and correlation:

```bash
MAX_PORTFOLIO_EXPOSURE=0.30          # Max 30% of portfolio in trades
MAX_CORRELATED_POSITIONS=2           # Max 2 correlated positions
```

**Example:** If exposure > 30%, leverage reduced by 30%

---

### **Recovery Mode**
Gradual leverage increase after losses:

```bash
RECOVERY_LOSS_TRIGGER=200.0          # Activate recovery after $200 loss
```

**Recovery Steps:** 5x → 8x → 12x → 15x → 20x → 25x → 30x

---

### **Time-Based Protection**
Reduces leverage during risky hours:

```bash
NIGHT_HOURS_START=22                 # Night hours start (22:00 UTC)
NIGHT_HOURS_END=6                    # Night hours end (06:00 UTC)
NIGHT_MAX_LEVERAGE=15                # Max leverage at night
WEEKEND_MAX_LEVERAGE=10              # Max leverage on weekends
```

**Example:** Trading at 23:00 UTC = max 15x leverage

---

## 📊 Decision Matrix

The system calculates a **Confidence Score (0-10)** based on:

| Factor | Weight | Score Calculation |
|--------|--------|-------------------|
| **Trade Quality** | 30% | Direct from AI (0-10) |
| **Market Regime** | 25% | TRENDING=10, VOLATILE=6, CHOPPY=4, CRASH=1 |
| **Symbol Tier** | 20% | Tier A=10, B=7, C=4, D=2, Blacklist=0 |
| **Win Rate** | 15% | 60%+ = 10, 50% = 5, 30% = 3 |
| **Volatility** | 10% | Low ATR = 10, High ATR = 2 |

### **Leverage Mapping**

| Confidence Score | Leverage Range | Example |
|-----------------|----------------|---------|
| **9.0-10.0** | 28-35x | TRENDING + Quality 9+ + Tier A |
| **8.0-8.9** | 20-28x | VOLATILE + Quality 8+ + Tier B |
| **7.0-7.9** | 15-20x | CHOPPY + Quality 7+ + Tier B |
| **6.0-6.9** | 10-15x | Quality 6+ + Tier C |
| **5.0-5.9** | 5-10x | Quality 5+ + Recovery Mode |
| **< 5.0** | 2-5x | Low Quality/Recovery |

---

## 🎯 Symbol Tier System

Symbols are automatically tiered based on performance:

| Tier | Win Rate | Leverage Impact |
|------|----------|-----------------|
| **Tier A** | > 60% | Full leverage (up to 35x) |
| **Tier B** | 45-60% | Good leverage (up to 28x) |
| **Tier C** | 30-45% | Limited leverage (max 8x) |
| **Tier D** | < 30% | Very limited (max 5x) |
| **Blacklist** | 3+ losses | No trading (0x) |

**Auto-Blacklist:** 3 consecutive losses = 30-day automatic blacklist

---

## 📍 Market Regime Detection

The system detects market conditions automatically:

| Regime | Detection Criteria | Leverage Range |
|--------|-------------------|----------------|
| **TRENDING** | ADX > 30 or ATR < 1.5% | 25-35x |
| **VOLATILE** | ATR > 3% | 15-25x |
| **CHOPPY** | ADX < 20 | 8-15x |
| **CRASH** | ATR > 5% | 3-8x |

---

## 💼 Position Sizing

Position size adapts to leverage:

| Leverage | Position Size | Example (10k portfolio) |
|----------|---------------|------------------------|
| **> 25x** | 1% | $100 position |
| **15-25x** | 2% | $200 position |
| **< 15x** | 3-5% | $300-500 position |

---

## 🔄 Integration with Existing System

### **Automatic Fallback**

If Dynamic Leverage fails or is disabled, the system automatically falls back to `leverage_policy.py`:

```python
# Example call in your code:
from utils.leverage_policy import adjust_leverage

leverage = adjust_leverage(
    adx=35.0,
    proposed=15,
    symbol="BTCUSDT",
    quality=9.0,              # Required for Dynamic
    atr_pct=0.018,           # Required for Dynamic
    current_price=50000,     # Required for Dynamic
    win_rate=0.65            # Optional
)
```

**If `DYNAMIC_LEVERAGE_MODE=1`:** Uses intelligent scoring  
**If `DYNAMIC_LEVERAGE_MODE=0`:** Uses static policy

---

## 📈 Example Scenarios

### **Scenario 1: High-Confidence TRENDING Trade**
```
Quality: 9/10
Market: TRENDING (ADX 35)
Symbol: BTCUSDT (Tier A, 65% win rate)
ATR: 1.8%

→ Confidence Score: 9.2/10
→ Base Leverage: 28-35x
→ Final Leverage: 32x ✅
```

### **Scenario 2: Medium Trade in VOLATILE Market**
```
Quality: 6/10
Market: VOLATILE (ATR 3.5%)
Symbol: ETHUSDT (Tier B, 55% win rate)
ATR: 3.5%

→ Confidence Score: 6.5/10
→ Base Leverage: 10-15x
→ Volatility Guard: Max 12x
→ Final Leverage: 12x ⚖️
```

### **Scenario 3: Weak Trade + Emergency Brake**
```
Quality: 4/10
Market: CHOPPY
Symbol: XRPUSDT (Tier C, 35% win rate)
Win Rate: 28% (< 30% threshold)

→ Confidence Score: 3.8/10
→ Base Leverage: 2-5x
→ Emergency Brake: Max 5x
→ Final Leverage: 5x 🛡️
```

---

## 🔧 Troubleshooting

### **Issue: Dynamic Leverage not activating**

**Check:**
1. `DYNAMIC_LEVERAGE_MODE=1` in Environment Variables
2. Logs show: `🚀 Dynamic Leverage v2.0 ENABLED`
3. All required parameters passed: `quality`, `atr_pct`, `current_price`

**Fallback Trigger:**
- Missing `current_price` → Falls back to static
- Import error → Falls back to static
- Any exception → Falls back to static

---

### **Issue: Leverage too conservative**

**Possible causes:**
1. **Safety guards active** → Check win rate, consecutive losses, daily loss
2. **Recovery mode** → System limiting leverage after losses
3. **Time protection** → Night hours or weekend
4. **Symbol blacklisted** → 3+ consecutive losses

**Check logs for:**
```
🚨 EMERGENCY BRAKE: Win rate 28% < 30%
🛡️ RECOVERY MODE: Step 2/7 → Max 8x
⏰ TIME PROTECTION: Night hours → Max 15x
```

---

### **Issue: Performance tracking not working**

**Solution:** Performance tracking is in-memory by default. To persist across restarts, ensure Redis is configured:

```bash
REDIS_URL=redis://your-upstash-url
```

---

## 📊 Monitoring

### **Check System Status**
```python
from utils.dynamic_leverage import get_dynamic_leverage_calculator

calc = get_dynamic_leverage_calculator()
stats = calc.get_leverage_stats()

# Output:
# {
#     "enabled": True,
#     "leverage_range": "2-35x",
#     "tracked_symbols": 15,
#     "blacklisted_symbols": 2,
#     "recovery_mode": False,
#     "recovery_step": 0
# }
```

---

## 🎯 Best Practices

1. **Start Conservative:** Begin with `DYNAMIC_MAX_LEVERAGE=20` and increase gradually
2. **Monitor First Week:** Track leverage decisions and safety guard activations
3. **Adjust Thresholds:** Fine-tune `EMERGENCY_WIN_RATE`, `VOLATILITY_EXTREME_ATR` based on your risk tolerance
4. **Check Logs:** Review `🚀 Dynamic Leverage` logs daily
5. **Recovery Mode:** Let it complete naturally (don't force-disable)

---

## 🚨 Important Notes

1. **Redis Required for Persistence:** Without Redis, performance tracking resets on restart
2. **Database Not Required:** System works without DB (uses in-memory cache)
3. **Fallback Always Available:** If Dynamic fails, static policy takes over
4. **No Manual Intervention:** System manages itself automatically

---

## 📞 Support

If you encounter issues:
1. Check Render logs for `🚀 Dynamic Leverage` entries
2. Verify all required environment variables are set
3. Ensure Redis is connected (optional but recommended)
4. Review safety guard activations in logs

**Example Log:**
```
🚀 Dynamic Leverage v2.0 initialized | Range: 2-35x | Enabled: True
🎯 BTCUSDT: Leverage 32x | Confidence: 9.2/10 | Guards: 0
```

---

**🎉 You're ready to use Dynamic Leverage v2.0!**
