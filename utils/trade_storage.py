from utils.trade_storage import save_trade  # <- חדש

# אחרי ההצלחה בטרייד:
save_trade({
    "symbol": symbol,
    "entry": entry,
    "stop": stop,
    "tp": tp,
    "direction": direction.upper(),
    "leverage": leverage,
    "confidence": 90,
    "quality_score": 5,
    "type": "REGULAR"
})





