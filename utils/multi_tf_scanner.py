# ===== קובץ: utils/multi_tf_scanner.py =====

import asyncio
from scanner_utils import scan_all
from utils.ai_analysis import analyze_with_ai
from utils.watchlist_utils import add_to_watchlist

async def multi_tf_scan(
    timeframes=("1m", "3m", "5m", "15m", "1h"),
    markets=("futures", "spot"),
    min_quality=6,
    top=10,
    trending_only=False
):
    all_trades = []
    tasks = []
    for tf in timeframes:
        for market in markets:
            tasks.append(scan_all(market_type=market, interval=tf, min_quality=min_quality, top=top, trending_only=trending_only))
    results = await asyncio.gather(*tasks)
    seen = set()
    merged = []
    for i, trades in enumerate(results):
        if not trades:
            continue
        tf = timeframes[i // len(markets)]
        for t in trades:
            key = (t["symbol"], t["direction"])
            if key not in seen:
                merged.append({**t, "markets": [t.get("market_type")], "frames": [tf]})
                seen.add(key)
            else:
                for m in merged:
                    if m["symbol"] == t["symbol"] and m["direction"] == t["direction"]:
                        m["markets"].append(t.get("market_type"))
                        m["frames"].append(tf)
                        break
    merged = sorted(
        merged,
        key=lambda x: (x.get("quality_score", 0), len(x.get("frames", [])), x.get("volume", 0)),
        reverse=True
    )
    # VIP Watchlist: כל מי שיש לו לפחות 2 frames
    for t in merged:
        if len(t.get("frames", [])) >= 2:
            add_to_watchlist(
                t["symbol"], t["direction"], t.get("quality_score", 0),
                reason=f"Confluence: {t.get('frames', [])}"
            )
    return merged[:top]

async def multi_tf_scan_with_ai(
    timeframes=("1m", "3m", "5m", "15m", "1h"),
    markets=("futures", "spot"),
    min_quality=6,
    top=10,
    trending_only=False
):
    trades = await multi_tf_scan(timeframes=timeframes, markets=markets, min_quality=min_quality, top=top, trending_only=trending_only)
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


