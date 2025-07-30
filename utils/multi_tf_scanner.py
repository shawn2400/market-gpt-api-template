# utils/multi_tf_scanner.py — גרסה עדכנית

import asyncio
from utils.trending_utils import get_trending_symbols
from utils.scanner_utils import analyze_symbol
from collections import defaultdict

async def multi_tf_scan_with_ai(
    timeframes=("1m","3m","5m","15m"),
    markets=("futures",),
    min_quality=6,
    top=10,
    trending_only=False,
    trending_source="coingecko"
):
    all_symbols = get_trending_symbols(source=trending_source, market_types=markets)
    if not all_symbols:
        return []

    results = defaultdict(list)
    tasks=[]
    for tf in timeframes:
        for s in all_symbols:
            tasks.append(analyze_symbol(s, market_type=markets[0], interval=tf, limit=50, trending_only=trending_only, with_ai=True, frames=[tf]))

    raw = await asyncio.gather(*tasks)
    for r in raw:
        if r and r["quality_score"]>=min_quality:
            sym=r["symbol"]; frm=r["frames"][0]
            results[sym].append(r)

    out=[]
    for sym, lst in results.items():
        if len(lst)>=2:
            dirs=[x["direction"] for x in lst]
            main= max(set(dirs), key=dirs.count)
            avg_q = sum(x["quality_score"] for x in lst if x["direction"]==main)/len(lst)
            out.append({
                "symbol":sym,
                "confluence":len(lst),
                "main_direction":main,
                "avg_quality":round(avg_q,2),
                "frames":[x["frames"][0] for x in lst],
                "details":lst
            })

    out.sort(key=lambda x:(-x["avg_quality"],-x["confluence"]))
    return out[:top]




