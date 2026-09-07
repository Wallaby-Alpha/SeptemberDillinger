"""
WEEX Symbol Resolver for MEXC Accumulation Scanner.
Maps MEXC Spot pairs (e.g., 'PEPE/USDT', 'LIT/USDT') to WEEX V3 Contract symbols
(e.g., '1000PEPEUSDT'), handling multiplier conversions, base asset normalization,
and safely identifying unlisted pairs.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import re
import time
from typing import Any, Dict, Optional, Set

from weex_client import WeexClient

logger = logging.getLogger("WEEX_RESOLVER")


@dataclass
class ResolvedWeexSymbol:
    weex_symbol: str           # e.g. 'BTCUSDT' or '1000PEPEUSDT'
    base_asset: str            # e.g. 'PEPE'
    quote_asset: str           # 'USDT'
    multiplier: float          # 1.0, 1000.0, etc.
    price_precision: int       # e.g. 4
    quantity_precision: int    # e.g. 2
    min_order_size: float      # e.g. 0.001
    contract_val: float        # e.g. 1.0
    max_leverage: int          # e.g. 50


class WeexSymbolResolver:
    def __init__(self, client: WeexClient, cache_ttl_seconds: int = 3600):
        self.client = client
        self.cache_ttl_seconds = cache_ttl_seconds
        self._markets_cache: Dict[str, Dict[str, Any]] = {}
        self._api_symbols_cache: Set[str] = set()
        self._last_refresh: float = 0.0

    def refresh_markets(self, force: bool = False) -> None:
        """Fetch all active WEEX contract markets and API whitelist with TTL caching."""
        now = time.time()
        if not force and self._markets_cache and (now - self._last_refresh < self.cache_ttl_seconds):
            return

        try:
            markets = self.client.get_exchange_info()
            if markets:
                self._markets_cache = markets
            api_symbols = self.client.get_api_trading_symbols()
            if api_symbols:
                self._api_symbols_cache = api_symbols
            self._last_refresh = now
            logger.info(f"[WEEX_RESOLVER] Cached {len(self._markets_cache)} markets and {len(self._api_symbols_cache)} API-whitelisted symbols.")
        except Exception as e:
            logger.error(f"[WEEX_RESOLVER] Failed to refresh WEEX markets: {e}")

    def resolve(self, mexc_symbol: str) -> Optional[ResolvedWeexSymbol]:
        """
        Translates a MEXC spot symbol to WEEX contract symbol.
        Returns ResolvedWeexSymbol if listed, or None if token is unlisted on WEEX.
        """
        self.refresh_markets()

        if not self._markets_cache:
            return None

        # Clean input symbol (e.g., 'LIT/USDT' -> 'LIT', '1000PEPE/USDT' -> '1000PEPE')
        clean = mexc_symbol.upper().replace("/USDT:USDT", "").replace("/USDT", "").replace("_USDT", "").replace("USDT", "")
        clean = clean.split("/")[0]

        # Extract numerical prefix if MEXC had one (e.g. 1000PEPE -> 1000, PEPE)
        match = re.match(r"^(\d+)?([A-Z0-9]+)$", clean)
        if match:
            prefix_str, core_base = match.groups()
            existing_multiplier = float(prefix_str) if prefix_str else 1.0
        else:
            existing_multiplier = 1.0
            core_base = clean

        # Candidates to evaluate in priority order
        candidates = [
            # 1. Exact base match
            (f"{core_base}USDT", 1.0),
            # 2. If MEXC already had a multiplier
            (f"{clean}USDT", existing_multiplier),
            # 3. 1,000x multiplier (very common on meme coins / low satoshi tokens)
            (f"1000{core_base}USDT", 1000.0),
            # 4. 10,000x multiplier
            (f"10000{core_base}USDT", 10000.0),
            # 5. 1,000,000x multiplier (e.g. AIDOGE, BABYDOGE)
            (f"1000000{core_base}USDT", 1000000.0),
        ]

        for cand_sym, mult in candidates:
            if cand_sym in self._markets_cache:
                # Validate against official WEEX API trading whitelist
                if self._api_symbols_cache and cand_sym not in self._api_symbols_cache:
                    logger.info(f"[WEEX_RESOLVER] {cand_sym} is listed on WEEX but NOT supported for API trading. Skipping.")
                    continue

                meta = self._markets_cache[cand_sym]
                return ResolvedWeexSymbol(
                    weex_symbol=cand_sym,
                    base_asset=core_base,
                    quote_asset="USDT",
                    multiplier=mult,
                    price_precision=meta.get("pricePrecision", 4),
                    quantity_precision=meta.get("quantityPrecision", 2),
                    min_order_size=meta.get("minOrderSize", 0.001),
                    contract_val=meta.get("contractVal", 1.0),
                    max_leverage=meta.get("maxLeverage", 50),
                )

        # Token not listed on WEEX
        return None

    def is_listed_on_weex(self, mexc_symbol: str) -> bool:
        """Helper to check if a MEXC symbol is active on WEEX Contracts."""
        return self.resolve(mexc_symbol) is not None
