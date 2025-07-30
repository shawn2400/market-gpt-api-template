import asyncio
from utils.trending_utils import get_trending_symbols
from utils.scanner_utils import analyze_symbol
from collections import defaultdict

async def multi_tf_scan_with_ai(
    timeframes=("1m", "3m", "5m", "15m"),
    min_quality=6,
    top=10,
    trending_source="coingecko",
    market_type="futures"
):
    """
    סורק סמלים Trending ביותר מטיימפריים, מחזיר מטבעות עם 'Confluence' (אישור במספר פריימים).
    :param timeframes: tuple/list, טיימפריימים לסריקה
    :param min_quality: int, סף איכות מינימלי
    :param top: int, כמה מטבעות מובילים להחזיר
    :param trending_source: str, מקור ה־Trending ("coingecko" / "coinmarketcap")
    :param market_type: str, "futures" / "spot"
    :return: list of dicts, כל מטבע כולל סיכום כיוונים ואיכות
    """
    # שליפת Trending (מסנן רק מטבעות זמינים במסחר)
    trending = get_trending_symbols(trending_source=trending_source, market_type=market_type)
    if not trending:
        return []

    # הכנה לסריקה
    results = defaultdict(list)
    tasks = []

    # סריקה אסינכרונית על כל שילוב symbol+tf
    for tf in timeframes:
        for symbol in trending:
            tasks.append(
                analyze_symbol(
                    symbol=symbol,
                    market_type=market_type,
                    interval=tf,
                    limit=50,
                    with_ai=True,
                    frames=[tf]
                )
            )

    raw_results = await asyncio.gather(*tasks)

    # איסוף וסינון לפי איכות וכיוון
    for r in raw_results:
        if (
            r and
            r.get("quality_score", 0) >= min_quality and
            r.get("direction") in ("LONG", "SHORT")
        ):
            frame = r.get("frames", [None])[0] if "frames" in r else None
            results[r["symbol"]].append({
                "frame": frame,
                "direction": r["direction"],
                "quality_score": r["quality_score"],
                "sl": r.get("sl"),
                "tp": r.get("tp"),
                "volume": r.get("volume"),
            })

    # מסנן רק מטבעות עם לפחות 2 טיימפריימים (confluence)
    filtered = []
    for symbol, frames in results.items():
        if len(frames) >= 2:
            # רוב כיוון
            dirs = [f["direction"] for f in frames]
            main_dir = max(set(dirs), key=dirs.count)
            avg_quality = (
                sum(f["quality_score"] for f in frames if f["direction"] == main_dir) / len(frames)
            )
            filtered.append({
                "symbol": symbol,
                "confluence": len(frames),
                "main_direction": main_dir,
                "avg_quality": round(avg_quality, 2),
                "frames": [f["frame"] for f in frames],
                "details": frames
            })

    # ממיין לפי איכות ממוצעת ואז confluence
    filtered = sorted(filtered, key=lambda x: (-x["avg_quality"], -x["confluence"]))

    return filtered[:top]



