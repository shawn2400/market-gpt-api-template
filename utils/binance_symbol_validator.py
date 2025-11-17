# -*- coding: utf-8 -*-
# utils/binance_symbol_validator.py
"""
Binance Symbol Precision & Validation
Fetches and caches exchange info to validate orders before submission
"""
import logging
import time
from typing import Dict, Optional, Tuple
from decimal import Decimal, ROUND_DOWN
import requests

logger = logging.getLogger("algogpt.symbol_validator")


class BinanceSymbolValidator:
    """
    Validates order parameters against Binance exchange rules.
    Caches symbol info to avoid repeated API calls.
    """
    
    def __init__(self):
        self.symbol_info_cache: Dict[str, Dict] = {}
        self.cache_timestamp = 0
        self.cache_ttl = 3600  # 1 hour
        self.base_url = "https://fapi.binance.com"
        logger.info("📊 Binance Symbol Validator initialized")
    
    def _fetch_exchange_info(self) -> Dict:
        """Fetch fresh exchange info from Binance"""
        try:
            url = f"{self.base_url}/fapi/v1/exchangeInfo"
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            # Build cache
            cache = {}
            for symbol_data in data.get("symbols", []):
                symbol = symbol_data["symbol"]
                
                # Extract filters
                filters = {f["filterType"]: f for f in symbol_data.get("filters", [])}
                
                cache[symbol] = {
                    "symbol": symbol,
                    "status": symbol_data.get("status"),
                    "baseAsset": symbol_data.get("baseAsset"),
                    "quoteAsset": symbol_data.get("quoteAsset"),
                    "pricePrecision": symbol_data.get("pricePrecision", 2),
                    "quantityPrecision": symbol_data.get("quantityPrecision", 3),
                    "baseAssetPrecision": symbol_data.get("baseAssetPrecision", 8),
                    "quotePrecision": symbol_data.get("quotePrecision", 8),
                    
                    # PRICE_FILTER
                    "minPrice": float(filters.get("PRICE_FILTER", {}).get("minPrice", 0)),
                    "maxPrice": float(filters.get("PRICE_FILTER", {}).get("maxPrice", 999999)),
                    "tickSize": float(filters.get("PRICE_FILTER", {}).get("tickSize", 0.01)),
                    
                    # LOT_SIZE
                    "minQty": float(filters.get("LOT_SIZE", {}).get("minQty", 0)),
                    "maxQty": float(filters.get("LOT_SIZE", {}).get("maxQty", 999999)),
                    "stepSize": float(filters.get("LOT_SIZE", {}).get("stepSize", 1)),
                    
                    # MIN_NOTIONAL
                    "minNotional": float(filters.get("MIN_NOTIONAL", {}).get("notional", 5)),
                    
                    # MARKET_LOT_SIZE (for market orders)
                    "marketMinQty": float(filters.get("MARKET_LOT_SIZE", {}).get("minQty", 0)),
                    "marketMaxQty": float(filters.get("MARKET_LOT_SIZE", {}).get("maxQty", 999999)),
                    "marketStepSize": float(filters.get("MARKET_LOT_SIZE", {}).get("stepSize", 1)),
                }
            
            self.symbol_info_cache = cache
            self.cache_timestamp = time.time()
            logger.info(f"✅ Fetched exchange info for {len(cache)} symbols")
            return cache
            
        except Exception as e:
            logger.error(f"Failed to fetch exchange info: {e}")
            return {}
    
    def get_symbol_info(self, symbol: str) -> Optional[Dict]:
        """
        Get symbol info from cache or fetch if needed.
        
        Args:
            symbol: Trading symbol (e.g., 'BTCUSDT')
            
        Returns:
            Symbol info dict or None if not found
        """
        # Refresh cache if expired
        if time.time() - self.cache_timestamp > self.cache_ttl:
            self._fetch_exchange_info()
        
        # Lazy load on first access
        if not self.symbol_info_cache:
            self._fetch_exchange_info()
        
        return self.symbol_info_cache.get(symbol)
    
    def round_price(self, symbol: str, price: float) -> float:
        """
        Round price to correct precision for symbol.
        
        Args:
            symbol: Trading symbol
            price: Raw price
            
        Returns:
            Rounded price matching Binance tick size
        """
        info = self.get_symbol_info(symbol)
        if not info:
            logger.warning(f"No symbol info for {symbol}, using raw price")
            return round(price, 4)
        
        tick_size = info["tickSize"]
        precision = info["pricePrecision"]
        
        # Round to tick size
        decimal_price = Decimal(str(price))
        decimal_tick = Decimal(str(tick_size))
        rounded = (decimal_price / decimal_tick).quantize(Decimal('1'), rounding=ROUND_DOWN) * decimal_tick
        
        # FIX: Use Decimal(10)**-precision instead of string pattern
        return float(rounded.quantize(Decimal(10)**-precision, rounding=ROUND_DOWN))
    
    def round_quantity(self, symbol: str, quantity: float, is_market: bool = False) -> float:
        """
        Round quantity to correct precision for symbol.
        
        Args:
            symbol: Trading symbol
            quantity: Raw quantity
            is_market: True for market orders (uses MARKET_LOT_SIZE)
            
        Returns:
            Rounded quantity matching Binance step size
        """
        info = self.get_symbol_info(symbol)
        if not info:
            logger.warning(f"No symbol info for {symbol}, using raw quantity")
            return round(quantity, 3)
        
        step_size = info["marketStepSize"] if is_market else info["stepSize"]
        precision = info["quantityPrecision"]
        
        # Round to step size
        decimal_qty = Decimal(str(quantity))
        decimal_step = Decimal(str(step_size))
        rounded = (decimal_qty / decimal_step).quantize(Decimal('1'), rounding=ROUND_DOWN) * decimal_step
        
        # FIX: Use Decimal(10)**-precision instead of string pattern
        return float(rounded.quantize(Decimal(10)**-precision, rounding=ROUND_DOWN))
    
    def validate_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: Optional[float] = None,
        is_market: bool = False
    ) -> Tuple[bool, Optional[str], Dict]:
        """
        Validate order parameters before sending to Binance.
        
        Args:
            symbol: Trading symbol
            side: BUY or SELL
            quantity: Order quantity
            price: Order price (None for market orders)
            is_market: True for market orders
            
        Returns:
            Tuple of (is_valid, error_message, corrected_params)
        """
        info = self.get_symbol_info(symbol)
        if not info:
            return False, f"Symbol {symbol} not found in exchange info", {}
        
        # Check symbol status
        if info["status"] != "TRADING":
            return False, f"Symbol {symbol} is not TRADING (status: {info['status']})", {}
        
        # Round to correct precision
        rounded_qty = self.round_quantity(symbol, quantity, is_market)
        rounded_price = self.round_price(symbol, price) if price else None
        
        # Validate quantity
        min_qty = info["marketMinQty"] if is_market else info["minQty"]
        max_qty = info["marketMaxQty"] if is_market else info["maxQty"]
        
        if rounded_qty < min_qty:
            return False, f"Quantity {rounded_qty} < minQty {min_qty}", {}
        
        if rounded_qty > max_qty:
            return False, f"Quantity {rounded_qty} > maxQty {max_qty}", {}
        
        # Validate price (for limit orders)
        if price and rounded_price:
            if rounded_price < info["minPrice"]:
                return False, f"Price {rounded_price} < minPrice {info['minPrice']}", {}
            
            if rounded_price > info["maxPrice"]:
                return False, f"Price {rounded_price} > maxPrice {info['maxPrice']}", {}
        
        # Validate notional (quantity * price)
        if is_market:
            # For market orders, we can't validate notional without current price
            # Binance will reject if below minimum
            pass
        elif price and rounded_price:
            notional = rounded_qty * rounded_price
            if notional < info["minNotional"]:
                return False, f"Notional {notional:.2f} < minNotional {info['minNotional']}", {}
        
        # Return corrected params
        corrected = {
            "symbol": symbol,
            "quantity": rounded_qty,
            "price": rounded_price,
        }
        
        logger.debug(
            f"✅ Order validated: {symbol} {side} qty={rounded_qty} "
            f"price={rounded_price} notional={rounded_qty * (rounded_price or 1):.2f}"
        )
        
        return True, None, corrected


# Singleton instance
_validator_instance: Optional[BinanceSymbolValidator] = None


def get_symbol_validator() -> BinanceSymbolValidator:
    """Get singleton validator instance"""
    global _validator_instance
    if _validator_instance is None:
        _validator_instance = BinanceSymbolValidator()
    return _validator_instance
