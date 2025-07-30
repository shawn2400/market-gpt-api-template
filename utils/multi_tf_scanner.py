# utils/multi_tf_scanner.py

import asyncio
from collections import defaultdict
from utils.trending_utils import get_trending_symbols
from utils.scanner_utils import analyze_symbol
from utils.ai_analysis import analyze_with_ai


async def multi_tf_scan_with_ai(
    timeframes=("5m", "15m", "1h"),
    markets=("futures", "spot"),
    min_quality=6,
    top=10,
    trending_only=False,
    trending_source="coingecko"
):
    symbols = set()
    for market in markets:
        syms = get_trending_symbols(trending_source=trending_source, market_type=market)
        symbols.update(syms)

    if not symbols:
        return []

    results = defaultdict(list)
    tasks = []
    for tf in timeframes:
        for symbol in symbols:
            tasks.append(analyze_symbol(
                symbol=symbol,
                market_type=markets[0],
                interval=tf,
                limit=50,
                trending_only=trending_only,
                with_ai=False,
                frames=[tf]
            ))

    raw = await asyncio.gather(*tasks)
    for r in raw:
        if r and r.get("quality_score", 0) >= min_quality:
            results[r["symbol"]].append(r)

    output = []
    for sym, entries in results.items():
        if len(entries) >= 2:
            directions = [x["direction"] for x in entries]
            main_dir = max(set(directions), key=directions.count)
            avg_q = sum(x["quality_score"] for x in entries if x["direction"] == main_dir) / len(entries)

            ai_data = {
                "rsi": entries[-1].get("rsi", 50),
                "adx": entries[-1].get("adx", 20),
                "trend": main_dir,
                "pattern": "unknown",
                "volume": entries[-1].get("volume", 1_000_000)
            }
            ai_res = analyze_with_ai(ai_data)
            if ai_res and not ai_res.get("error") and (main_dir in ai_res["answer"]):
                output.append({
                    "symbol": sym,
                    "confluence": len(entries),
                    "main_direction": main_dir,
                    "avg_quality": round(avg_q, 2),
                    "frames": [x["frames"][0] for x in entries],
                    "ai_opinion": ai_res["answer"],
                    "ai_score": ai_res.get("score", 1.0),
                    "details": entries
                })

    output.sort(key=lambda x: (-x["avg_quality"], -x["ai_score"]))
    return output[:top]






