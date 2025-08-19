# utils/orderflow.py
from __future__ import annotations
import os
from typing import Dict, Any
import httpx

_FAPI = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com").rstrip("/")

async def get_orderflow_snapshot(symbol: str, trades_limit: int = 800, depth_limit: int = 500, cvd_window: int = 300) -> Dict[str, Any]:
    sym = symbol.upper().strip()
    async with httpx.AsyncClient(timeout=10.0) as client:
        # ספרד/דאפ׳
        depth = await client.get(f"{_FAPI}/fapi/v1/depth", params={"symbol": sym, "limit": depth_limit})
        depth.raise_for_status()
        d = depth.json()
        bids = [(float(p), float(q)) for p, q in d.get("bids", [])]
        asks = [(float(p), float(q)) for p, q in d.get("asks", [])]
        best_bid = bids[0][0] if bids else None
        best_ask = asks[0][0] if asks else None
        bid_vol = sum(q for _, q in bids)
        ask_vol = sum(q for _, q in asks)
        imbalance = (bid_vol - ask_vol) / max(1e-9, (bid_vol + ask_vol))

        # 24h (טייקר)
        stat = await client.get(f"{_FAPI}/fapi/v1/ticker/24hr", params={"symbol": sym})
        stat.raise_for_status()
        s = stat.json()
        taker_buy = float(s.get("takerBuyBaseVolume", 0.0))
        volume = float(s.get("volume", 0.0))

        # aggTrades לחלון CVD
        trades = await client.get(f"{_FAPI}/fapi/v1/aggTrades", params={"symbol": sym, "limit": min(1000, trades_limit)})
        trades.raise_for_status()
        tjs = trades.json()
        # m = isBuyerMaker (True ⇒ הקונה הוא ה-maker ⇒ הטייקר היה מוכר)
        cvd = 0.0
        buy_count = sell_count = 0
        for t in tjs[-cvd_window:]:
            q = float(t.get("q", 0.0))
            is_buyer_maker = bool(t.get("m", False))
            if is_buyer_maker:
                # טייקר = SELL
                cvd -= q
                sell_count += 1
            else:
                # טייקר = BUY
                cvd += q
                buy_count += 1

        return {
            "ok": True,
            "symbol": sym,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "orderbook": {
                "bid_volume": bid_vol,
                "ask_volume": ask_vol,
                "imbalance": imbalance,
                "levels": {"bids": len(bids), "asks": len(asks)},
            },
            "trades": {
                "taker_buy_count": buy_count,
                "taker_sell_count": sell_count,
                "cvd_window": min(cvd_window, len(tjs)),
                "cvd": cvd,
            },
            "stats_24h": {
                "taker_buy_base_volume": taker_buy,
                "volume_base": volume,
            },
        }


