"""
MEXC REST API Client wrapper using CCXT.
Handles rate-limiting, error retries, ticker filtering, orderbook spread calculation,
and OHLCV fetching.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional
import ccxt
import pandas as pd


class MexcClient:
    def __init__(self, request_delay_seconds: float = 0.08):
        self.request_delay_seconds = request_delay_seconds
        self.exchange = ccxt.mexc({
            "enableRateLimit": True,
            "timeout": 20000,
            "options": {
                "defaultType": "spot",
            },
        })

    def fetch_spot_usdt_tickers(
        self,
        min_quote_volume: float = 250000.0,
        excluded_keywords: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Fetch all 24h Spot USDT tickers and filter out stablecoins, leverage tokens,
        and low-volume pairs.
        """
        if excluded_keywords is None:
            excluded_keywords = [
                "3L", "3S", "4L", "4S", "5L", "5S",
                "BEAR", "BULL", "DOWN", "UP",
                "USDC", "FDUSD", "TUSD", "BUSD", "DAI", "USDD", "USDE", "EUR", "TRY"
            ]

        try:
            raw_tickers = self.exchange.fetch_tickers()
        except Exception as e:
            print(f"[ERROR] Failed to fetch tickers from MEXC: {e}")
            return []

        filtered_tickers: List[Dict[str, Any]] = []

        for symbol, ticker in raw_tickers.items():
            # Check spot USDT format (e.g. 'ETH/USDT' or 'BTC/USDT:USDT')
            if not (symbol.endswith("/USDT") or symbol.endswith("/USDT:USDT")):
                continue

            base = symbol.split("/")[0].upper()

            # Filter excluded keywords in base currency
            if any(kw in base for kw in excluded_keywords):
                continue

            # Check 24h quote volume (in USDT)
            quote_volume = float(ticker.get("quoteVolume") or 0.0)
            if quote_volume < min_quote_volume:
                continue

            # Compute spread from ticker top bid/ask
            bid = float(ticker.get("bid") or 0.0)
            ask = float(ticker.get("ask") or 0.0)
            last_price = float(ticker.get("last") or ticker.get("close") or 0.0)

            if last_price <= 0:
                continue

            if bid > 0 and ask > 0 and ask >= bid:
                mid = (bid + ask) / 2.0
                spread_bps = ((ask - bid) / mid) * 10000.0
            else:
                spread_bps = 0.0

            filtered_tickers.append({
                "symbol": symbol,
                "base": base,
                "price": last_price,
                "quote_volume_24h": quote_volume,
                "bid": bid,
                "ask": ask,
                "spread_bps": spread_bps,
                "change_24h_pct": float(ticker.get("percentage") or 0.0),
            })

        # Sort descending by 24h quote volume
        filtered_tickers.sort(key=lambda x: x["quote_volume_24h"], reverse=True)
        return filtered_tickers

    def fetch_ohlcv_df(
        self,
        symbol: str,
        timeframe: str = "1h",
        limit: int = 120,
        retries: int = 3,
    ) -> Optional[pd.DataFrame]:
        """
        Fetch OHLCV candles from MEXC and return as pandas DataFrame.
        """
        for attempt in range(retries):
            try:
                if self.request_delay_seconds > 0:
                    time.sleep(self.request_delay_seconds)

                ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
                if not ohlcv or len(ohlcv) == 0:
                    return None

                df = pd.DataFrame(
                    ohlcv,
                    columns=["timestamp", "open", "high", "low", "close", "volume"]
                )
                df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
                df[["open", "high", "low", "close", "volume"]] = df[
                    ["open", "high", "low", "close", "volume"]
                ].astype(float)
                return df

            except (ccxt.NetworkError, ccxt.RateLimitExceeded) as e:
                wait_time = (attempt + 1) * 0.5
                time.sleep(wait_time)
                if attempt == retries - 1:
                    print(f"[WARN] Network error fetching {symbol} {timeframe}: {e}")
            except Exception as e:
                # Symbol might not exist or be delisted
                if attempt == retries - 1:
                    print(f"[WARN] Failed fetching {symbol} {timeframe}: {e}")
                break

        return None

    def fetch_orderbook_spread_bps(self, symbol: str) -> float:
        """Fetch real-time order book top bid/ask to calculate accurate spread in bps."""
        try:
            if self.request_delay_seconds > 0:
                time.sleep(self.request_delay_seconds)
            ob = self.exchange.fetch_order_book(symbol, limit=5)
            bids = ob.get("bids", [])
            asks = ob.get("asks", [])
            if bids and asks:
                best_bid = bids[0][0]
                best_ask = asks[0][0]
                if best_bid > 0 and best_ask >= best_bid:
                    mid = (best_bid + best_ask) / 2.0
                    return float(((best_ask - best_bid) / mid) * 10000.0)
        except Exception:
            pass
        return 0.0
