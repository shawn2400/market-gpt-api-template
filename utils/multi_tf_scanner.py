async def multi_tf_scan_with_ai(
    timeframes=("5m", "15m", "1h"),
    markets=("futures",),
    min_quality=6,
    top=10,
    trending_only=False,
    trending_source="coingecko"
):
    logging.info(f"[multi_tf_scanner] התחלת סריקה: tf={timeframes}, markets={markets}, min_quality={min_quality}, top={top}, trending_only={trending_only}")

    # שליפת סמלים טרנדיים (קריאה סינכרונית, בלי await)
    if trending_only:
        symbols = get_trending_symbols(trending_source=trending_source, market_type=markets[0])
        logging.info(f"[multi_tf_scanner] סמלים טרנדיים נבחרו: {symbols}")
    else:
        # אפשר להחליף כאן לטעינת watchlist אם רוצים
        symbols = get_trending_symbols(trending_source=trending_source, market_type=markets[0])

    if not symbols:
        logging.warning("[multi_tf_scanner] אין סמלים לסריקה")
        return []

    # הגבלת מספר סמלים
    symbols = symbols[:MAX_SYMBOLS]

    # סריקה אסינכרונית לכל סמל ולכל טיימפריים
    tasks = [safe_analyze(symbol, tf, markets[0], trending_only) for symbol in symbols for tf in timeframes]
    results_raw = await asyncio.gather(*tasks)
    results_raw = [r for r in results_raw if r]

    # קיבוץ תוצאות לפי סימבול
    grouped = {}
    for r in results_raw:
        sym = r["symbol"]
        grouped.setdefault(sym, []).append(r)

    # עיבוד תוצאות עם AI לכל סימבול
    final_results = []
    for sym, data in grouped.items():
        avg_quality = sum(d.get("quality_score", 0) for d in data) / len(data)
        if avg_quality < min_quality:
            continue

        ai_analysis = await analyze_with_ai(data)
        if "error" in ai_analysis:
            logging.warning(f"[multi_tf_scanner] ניתוח AI נכשל עבור {sym}: {ai_analysis['error']}")
            continue

        final_results.append(ai_analysis)

    # מיון לפי ציון איכות ולקיחת top N
    final_results.sort(key=lambda x: x.get("quality_score", 0), reverse=True)
    return final_results[:top]

































