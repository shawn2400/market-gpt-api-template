from utils.multi_tf_scanner import multi_tf_scan
from utils.ai_analysis import analyze_with_ai

async def multi_tf_scan_with_ai(
    timeframes=("5m", "15m", "1h"),
    markets=("futures", "spot"),
    min_quality=6,
    top=10,
    trending_only=False
):
    trades = await multi_tf_scan(
        timeframes=timeframes,
        markets=markets,
        min_quality=min_quality,
        top=top,
        trending_only=trending_only
    )
    filtered = []
    for t in trades:
        ai_data = {
            "rsi": t.get("rsi", 50),
            "adx": t.get("adx", 20),
            "trend": t.get("direction", "NEUTRAL"),
            "pattern": "unknown",
            "volume": t.get("volume", 1_000_000)
        }
        ai_res = analyze_with_ai(ai_data)
        if ai_res and not ai_res.get("error") and ("LONG" in ai_res["answer"] or "SHORT" in ai_res["answer"]):
            t["ai_second_opinion"] = ai_res["answer"]
            t["ai_score"] = ai_res.get("score", 0.9)
            filtered.append(t)
    return filtered

