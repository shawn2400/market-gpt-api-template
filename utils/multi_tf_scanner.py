# utils/multi_tf_scanner.py

import asyncio
from collections import defaultdict
from utils.trending_utils import get_trending_symbols
from utils.scanner_utils import analyze_symbol
from utils.ai_analysis import analyze_with_ai

async def multi_tf_scan_with_ai(
    timeframes: tuple[str, ...] = ("5m", "15m", "1h"),
    markets: tuple[str, ...] = ("futures", "spot"),
    min_quality: int = 6,
    top: int = 10,
    trending_only: bool = False,
    trending_source: str = "coingecko"
):
    # איסוף סמלים מכל שוק
    symbols = set()
    for m in markets:
        syms = get_trending_symbols(trending_source=trending_source, market_type=m)
        symbols.update(syms)
    if not symbols:
        return []

    results: dict[str, list[dict]] = defaultdict(list)
    tasks = []
    for tf in timeframes:
        for sym in symbols:
            tasks.append(
                analyze_symbol(
                    symbol=sym,
                    market_type=markets[0],
                    interval=tf,
                    limit=50,
                    trending_only=trending_only,
                    with_ai=False,   # עדיין לא נשתמש ב־AI כאן
                    frames=[tf]
                )
            )

    raw = await asyncio.gather(*tasks)
    for r in raw:
        if r and r["quality_score"] >= min_quality:
            sym = r["symbol"]
            results[sym].append(r)

    output = []
    for sym, lst in results.items():
        if len(lst) >= 2:
            dirs = [x["direction"] for x in lst]
            main = max(set(dirs), key=dirs.count)
            avg_q = sum(x["quality_score"] for x in lst if x["direction"] == main) / len(lst)

            ai_data = {
                "rsi": lst[-1].get("rsi", 50),
                "adx": lst[-1].get("adx", 20),
                "trend": main,
                "pattern": "unknown",
                "volume": lst[-1].get("volume", 1_000_000)
            }
            ai_res = analyze_with_ai(ai_data)
            ai_ok = ai_res and not ai_res.get("error") and ("LONG" in ai_res["answer"] or "SHORT" in ai_res["answer"])

            if ai_ok:
                output.append({
                    "symbol": sym,
                    "confluence": len(lst),
                    "main_direction": main,
                    "avg_quality": round(avg_q, 2),
                    "frames": [x["frames"][0] for x in lst],
                    "ai_opinion": ai_res["answer"],
                    "ai_score": ai_res.get("score", 1.0),
                    "details": lst
                })

    output.sort(key=lambda x: (-x["avg]()





