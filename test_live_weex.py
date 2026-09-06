import logging
from config import WeexConfig
from weex_client import WeexClient
from weex_resolver import WeexSymbolResolver

logging.basicConfig(level=logging.INFO)

c = WeexClient(WeexConfig())
r = WeexSymbolResolver(c)

test_pairs = [
    "BTC/USDT",
    "ETH/USDT",
    "SOL/USDT",
    "PEPE/USDT",
    "BONK/USDT",
    "LUNC/USDT",
    "LIT/USDT",       # Known unlisted
    "1000PEPE/USDT",  # Multiplier already in MEXC ticker
]

print("\n" + "=" * 50)
print("TESTING LIVE WEEX SYMBOL RESOLUTION")
print("=" * 50)

for p in test_pairs:
    res = r.resolve(p)
    if res:
        print(f"[FOUND] {p:<16} -> {res.weex_symbol:<16} (Multiplier: {res.multiplier}x, PricePrec: {res.price_precision})")
    else:
        print(f"[UNLISTED] {p:<16} -> UNLISTED ON WEEX (Safely Caught)")
print("=" * 50 + "\n")
