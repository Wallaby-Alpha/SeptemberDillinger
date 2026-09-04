"""
Quick live verification script for MEXC Spot REST API connectivity.
Fetches BTC/USDT 1h candles, samples top volume USDT tickers, and tests scoring.
"""

from __future__ import annotations

import sys
from config import ScannerConfig
from mexc_client import MexcClient
from scoring import calculate_quiet_accumulation_score, evaluate_hard_gates


def main():
    print("[TEST] Initializing MEXC Client...")
    cfg = ScannerConfig()
    client = MexcClient(request_delay_seconds=0.08)

    print("[TEST] Fetching BTC/USDT 1h baseline candles...")
    df_btc = client.fetch_ohlcv_df("BTC/USDT", timeframe="1h", limit=120)
    if df_btc is None or len(df_btc) == 0:
        print("[FAIL] Could not fetch BTC/USDT 1h candles from MEXC REST API.")
        sys.exit(1)

    btc_price = float(df_btc["close"].iloc[-1])
    print(f"[PASS] Successfully fetched BTC/USDT: {len(df_btc)} candles. Latest price: ${btc_price:,.2f}")

    print("\n[TEST] Fetching Top USDT Tickers...")
    tickers = client.fetch_spot_usdt_tickers(
        min_quote_volume=250000.0,
        excluded_keywords=cfg.excluded_keywords,
    )
    print(f"[PASS] Filtered active USDT pairs found: {len(tickers)}")

    # Sample top 5 tickers to test candle fetching & gate evaluations
    print("\n[TEST] Sampling top 5 pairs for gate evaluation and scoring:")
    for t in tickers[:5]:
        sym = t["symbol"]
        df_1h = client.fetch_ohlcv_df(sym, timeframe="1h", limit=120)
        df_1d = client.fetch_ohlcv_df(sym, timeframe="1d", limit=30)

        if df_1h is None:
            print(f"  • {sym:<12} -> Failed fetching 1h OHLCV")
            continue

        gate_res = evaluate_hard_gates(
            df_1h=df_1h,
            df_1d=df_1d,
            quote_volume_24h=t["quote_volume_24h"],
            spread_bps=t["spread_bps"],
            gates=cfg.gates,
        )

        score_res = calculate_quiet_accumulation_score(
            symbol=sym,
            df_alt_1h=df_1h,
            df_alt_1d=df_1d,
            df_btc_1h=df_btc,
            quote_volume_24h=t["quote_volume_24h"],
            spread_bps=t["spread_bps"],
            weights=cfg.weights,
            gates=cfg.gates,
        )

        print(
            f"  • {sym:<12} | Px: ${score_res.price:<10.4f} "
            f"| Gated: {'NO (Passed)' if gate_res.passed else 'YES (' + gate_res.reason + ')'} "
            f"| Score: {score_res.final_score:.2f} "
            f"| Phase: {score_res.stage}"
        )

    print("\n[SUCCESS] Live MEXC REST connectivity and scoring verified successfully.")


if __name__ == "__main__":
    main()
