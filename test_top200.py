from config import load_config
from mexc_client import MexcClient
from weex_client import WeexClient
from weex_resolver import WeexSymbolResolver

c = load_config()
m = MexcClient()
wx_c = WeexClient(c.weex)
resolver = WeexSymbolResolver(wx_c)

print("Fetching MEXC tickers with 24h volume >= $100,000...")
tickers = m.fetch_spot_usdt_tickers(min_quote_volume=100000)
print(f"Total pairs found: {len(tickers)}")

# Top 200 general
top200 = tickers[:200]
print(f"\nTop 200 MEXC pairs:")
print(f"  #1  Volume: ${top200[0]['quote_volume_24h']:,.0f} ({top200[0]['symbol']})")
print(f"  #200 Volume: ${top200[-1]['quote_volume_24h']:,.0f} ({top200[-1]['symbol']})")

# Check how many of the top 200 are listed on WEEX
resolver.refresh_markets()
listed_count = sum(1 for t in top200 if resolver.is_listed_on_weex(t["symbol"]))
print(f"\nOf the top 200 MEXC volume pairs, {listed_count} ({listed_count/200*100:.1f}%) are tradeable on WEEX Contracts.")

# If we strictly filter to WEEX-listed coins first:
weex_tradeable = [t for t in tickers if resolver.is_listed_on_weex(t["symbol"])]
print(f"\nIf using WEEX_ONLY_UNIVERSE=true:")
print(f"  Total tradeable pairs on both exchanges: {len(weex_tradeable)}")
print(f"  Top 200 WEEX-tradeable pairs volume range: ${weex_tradeable[0]['quote_volume_24h']:,.0f} down to ${weex_tradeable[min(199, len(weex_tradeable)-1)]['quote_volume_24h']:,.0f}")
