# utils/quality_score.py
def compute_quality_score(row):
    """
    חישוב ניקוד איכות לטרייד לפי תנאים טכניים
    טווח ניקוד: 0 עד 10
    """
    score = 0

    if row['rsi'] < 30 or row['rsi'] > 70:
        score += 2
    if row['macd'] > 0:
        score += 2
    if row['adx'] > 20:
        score += 2
    if 'volume' in row and 'atr' in row:
        if row['volume'] > row.get('volume_mean', row['volume'] * 0.95):
            score += 2
        if row['atr'] > 0:
            score += 2

    return min(score, 10)
