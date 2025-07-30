# ===== קובץ: utils/multi_tf_scanner.py =====

import asyncio
from scanner_utils import scan_all

async def multi_tf_scan(
    symbols=None,
    timeframes=("5m", "15m", "1h"),
    markets=("futures", "spot"),
    min_quality=6,
    top=10
):
    all_trades = []
    tasks = []

    for tf in timeframes:
        for market in markets:
            tasks.append(scan_all(market_type=market, interval=tf, min_quality=min_quality, top=top))

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
                # הוספת טיימפריים/מרקט נוספים לרשומה קיימת
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
    return merged[:top]
