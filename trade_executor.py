from utils.quantity_utils import calculate_quantity, auto_risk_allocation

def execute_trade_live(symbol, entry, stop, tp, direction, leverage, budget_usd=100, use_grid=False, use_trailing=False, user_id=None, take_snapshot=True):
    try:
        # שליפת חדשות וסנטימנט
        news = fetch_crypto_news()
        sentiment = analyze_news_impact(news)
        news_score = sum(n['impact_score'] for n in sentiment if symbol[:3].lower() in n['title'].lower())

        # שינוי מינוף
        client.futures_change_leverage(symbol=symbol, leverage=leverage)

        # מחיר עדכני
        price = get_live_price(symbol)
        if not price:
            raise ValueError("⚠️ לא ניתן לשלוף מחיר עדכני")

        # חיזוי SL/TP אם חסרים
        if not stop or not tp:
            sltp = predict_optimal_sl_tp(symbol, price, direction)
            stop = sltp["sl"]
            tp = sltp["tp"]

        # הקצאת סיכון וחישוב תקציב בפועל
        capital_used = auto_risk_allocation(entry_price=entry, stop_price=stop, total_budget=budget_usd)
        quantity = calculate_quantity(symbol, entry, leverage, capital_used)
        if quantity <= 0:
            raise ValueError("⚠️ כמות לא חוקית (יתכן תקציב או stepSize שגוי)")

        side = SIDE_BUY if direction.upper() == "LONG" else SIDE_SELL
        opposite = SIDE_SELL if side == SIDE_BUY else SIDE_BUY

        # פתיחת פוזיציה
        client.futures_create_order(
            symbol=symbol,
            side=side,
            type=ORDER_TYPE_MARKET,
            quantity=quantity
        )
        time.sleep(0.5)

        # הגדרת SL
        if use_trailing:
            activation_price = round(price * 1.005 if direction.upper() == "LONG" else price * 0.995, 4)
            client.futures_create_order(
                symbol=symbol,
                side=opposite,
                type=ORDER_TYPE_TRAILING_STOP_MARKET,
                callbackRate=2.0,
                activationPrice=activation_price,
                closePosition=True,
                timeInForce=TIME_IN_FORCE_GTC
            )
        else:
            client.futures_create_order(
                symbol=symbol,
                side=opposite,
                type=ORDER_TYPE_STOP_MARKET,
                stopPrice=round(stop, 4),
                closePosition=True,
                timeInForce=TIME_IN_FORCE_GTC
            )

        # הגדרת TP
        try:
            client.futures_create_order(
                symbol=symbol,
                side=opposite,
                type=ORDER_TYPE_LIMIT,
                price=round(tp, 4),
                quantity=quantity,
                timeInForce=TIME_IN_FORCE_GTC
            )
        except Exception as e:
            logging.warning(f"[!] טייק פרופיט נכשל: {e}")

        # צילום Snapshot
        snapshot_path = None
        if take_snapshot:
            snapshot_path = save_trade_snapshot({
                "symbol": symbol,
                "entry": entry,
                "stop": stop,
                "tp": tp,
                "direction": direction.upper()
            })

        # חישוב איכות ו־confidence
        df = pd.DataFrame([{
            "atr": abs(tp - stop),
            "macd": 1,
            "macd_signal": 0,
            "rsi": 50,
            "adx": 25,
            "volume": 1_000_000,
            "volume_mean": 800_000,
            "close": price,
            "ema_21": price * 0.99,
            "ema_50": price * 0.98
        }])
        quality = compute_quality_score(df)
        confidence = round(70 + 3 * quality + news_score * 2, 2)

        # שמירת טרייד
        trade_data = {
            "symbol": symbol,
            "entry": entry,
            "stop": stop,
            "tp": tp,
            "direction": direction.upper(),
            "leverage": leverage,
            "confidence": confidence,
            "quality_score": quality,
            "mock_quality": True,
            "type": "GRID" if use_grid else "REGULAR",
            "user_id": user_id or "default",
            "news_score": news_score,
            "capital_used": round(capital_used, 2),
            "quantity": quantity
        }
        save_trade(trade_data)

        # עדכון PNL
        update_pnl(symbol, direction, entry, price, leverage, quantity)

        # התראת מייל
        send_email_alert(
            subject=f"🔔 AlgoGPT Trade Executed: {symbol} {direction.upper()}",
            body=f"""Symbol: {symbol}
Direction: {direction}
Entry: {entry}
Stop: {stop}
TP: {tp}
Leverage: {leverage}
Confidence: {confidence:.2f}%
Quality: {quality}/10
News Score: {news_score}
Capital Used: {capital_used:.2f}$
Qty: {quantity}"""
        )

        return {
            "status": "success",
            "symbol": symbol,
            "entry": entry,
            "price_now": price,
            "quantity": quantity,
            "stop": stop,
            "tp": tp,
            "leverage": leverage,
            "side": side,
            "confidence": confidence,
            "quality_score": quality,
            "news_score": news_score,
            "snapshot": snapshot_path,
            "trailing": use_trailing,
            "grid": use_grid,
            "capital_used": capital_used
        }

    except Exception as e:
        logging.error(f"❌ שגיאה בביצוע טרייד ב־{symbol}: {e}")
        return {"status": "error", "message": str(e)}
























