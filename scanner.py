"""
Core Scanner Orchestrator for MEXC Quiet Accumulation setups.
Iterates across all active USDT spot pairs, enforces hard gates, calculates
Stage 1 Quiet Accumulation scores, logs candidates, and dispatches alerts.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import List, Optional

from config import ScannerConfig
from database import Database
from mexc_client import MexcClient
from scoring import (
    ScoringResult,
    calculate_quiet_accumulation_score,
    evaluate_hard_gates,
)
from telegram_alerts import TelegramAlertManager


class AccumulationScanner:
    def __init__(
        self,
        config: ScannerConfig,
        db: Optional[Database] = None,
        client: Optional[MexcClient] = None,
        telegram: Optional[TelegramAlertManager] = None,
    ):
        self.config = config
        self.db = db or Database(config.database_path)
        self.client = client or MexcClient(config.request_delay_seconds)
        self.telegram = telegram or TelegramAlertManager(
            config.telegram, self.db, config.cooldown_minutes
        )

    def scan_cycle(self) -> List[ScoringResult]:
        """
        Execute a complete scan cycle across MEXC Spot USDT pairs.
        Returns a list of alerts generated in this cycle.
        """
        start_time = time.time()
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        print("\n" + "═" * 70)
        print(f"🔍 SCAN CYCLE START — {now_str}")
        print(f"⚙️  Thresholds: Min Volume=${self.config.gates.min_24h_quote_volume:,.0f} | Alert Score ≥ {self.config.min_alert_score} | Cooldown={self.config.cooldown_minutes}m")
        print("═" * 70)

        # 1. Fetch BTC/USDT baseline 1h and 1d candles
        print("[INIT] Fetching BTC/USDT baseline candles for Relative Strength...")
        df_btc_1h = self.client.fetch_ohlcv_df("BTC/USDT", timeframe="1h", limit=120)
        if df_btc_1h is None or len(df_btc_1h) < 20:
            # Try alternate symbol notation
            df_btc_1h = self.client.fetch_ohlcv_df("BTC/USDT:USDT", timeframe="1h", limit=120)

        if df_btc_1h is None or len(df_btc_1h) < 20:
            print("[ERROR] Could not fetch BTC/USDT 1h candles. Aborting cycle.")
            return []

        btc_price = float(df_btc_1h["close"].iloc[-1])
        print(f"[INIT] BTC/USDT Reference Price: ${btc_price:,.2f} ({len(df_btc_1h)} 1h candles)")

        # 2. Fetch all Spot USDT tickers meeting volume filter
        print("[INIT] Fetching all active MEXC Spot USDT tickers...")
        tickers = self.client.fetch_spot_usdt_tickers(
            min_quote_volume=self.config.gates.min_24h_quote_volume,
            excluded_keywords=self.config.excluded_keywords,
        )

        total_tickers = len(tickers)
        print(f"[INIT] Found {total_tickers} active USDT pairs meeting volume filter (>= ${self.config.gates.min_24h_quote_volume:,.0f}).")

        gated_count = 0
        scored_count = 0
        alerted_results: List[ScoringResult] = []

        # 3. Process each candidate symbol
        for idx, ticker_info in enumerate(tickers, start=1):
            symbol = ticker_info["symbol"]
            quote_vol = ticker_info["quote_volume_24h"]
            spread_bps = ticker_info["spread_bps"]

            # Fetch 1h candles for symbol
            df_1h = self.client.fetch_ohlcv_df(symbol, timeframe="1h", limit=120)
            if df_1h is None:
                gated_count += 1
                continue

            # If spread was 0 or borderline, fetch live order book spread
            if spread_bps <= 0 or spread_bps > 60:
                ob_spread = self.client.fetch_orderbook_spread_bps(symbol)
                if ob_spread > 0:
                    spread_bps = ob_spread

            # Fetch daily candles for daily trend filter
            df_1d = self.client.fetch_ohlcv_df(symbol, timeframe="1d", limit=30)

            # Evaluate Hard Gates
            gate_res = evaluate_hard_gates(
                df_1h=df_1h,
                df_1d=df_1d,
                quote_volume_24h=quote_vol,
                spread_bps=spread_bps,
                gates=self.config.gates,
            )

            if not gate_res.passed:
                gated_count += 1
                # Format a compact single-line log for gated pairs
                # (keep console clean while remaining informative)
                # print(f"  [GATED] {symbol:<14} | Reason: {gate_res.reason}")
                continue

            # Calculate Stage 1 Quiet Accumulation Score
            score_res = calculate_quiet_accumulation_score(
                symbol=symbol,
                df_alt_1h=df_1h,
                df_alt_1d=df_1d,
                df_btc_1h=df_btc_1h,
                quote_volume_24h=quote_vol,
                spread_bps=spread_bps,
                weights=self.config.weights,
                gates=self.config.gates,
            )

            # Log candidate if above logging threshold
            if score_res.final_score >= self.config.min_log_score:
                scored_count += 1
                self.db.log_candidate(
                    symbol=score_res.symbol,
                    price=score_res.price,
                    final_score=score_res.final_score,
                    stage=score_res.stage,
                    passed_gates=True,
                    rs_score=score_res.rs_score,
                    vol_score=score_res.vol_score,
                    trend_score=score_res.trend_score,
                    liq_score=score_res.liq_score,
                    spread_bps=score_res.spread_bps,
                    quote_volume_24h=score_res.quote_volume_24h,
                )

                status_prefix = "  [SCORED]"
                if score_res.final_score >= self.config.min_alert_score and score_res.is_stage1:
                    status_prefix = "🔥 [CANDIDATE]"

                print(
                    f"{status_prefix} {symbol:<12} | Score: {score_res.final_score:.2f} "
                    f"| RS: {score_res.rs_score:.2f} (Diff: {score_res.rs_diff_pct:+.1f}%) "
                    f"| Vol: {score_res.vol_score:.2f} ({score_res.vol_ratio:.1f}x) "
                    f"| Trend: {score_res.trend_score:.2f} "
                    f"| Px: ${score_res.price:.4f}"
                )

            # Check Alert Criteria
            if score_res.final_score >= self.config.min_alert_score and score_res.is_stage1:
                # Check cooldown
                if not self.telegram.can_send_alert(symbol):
                    print(f"  [COOLDOWN] {symbol} high score ({score_res.final_score:.2f}) but in cooldown.")
                    continue

                # Dispatch Telegram alert
                alert_sent = self.telegram.send_alert(score_res)

                # Persist to alerts table in SQLite
                alert_id = self.db.save_alert(
                    symbol=score_res.symbol,
                    price=score_res.price,
                    final_score=score_res.final_score,
                    stage=score_res.stage,
                    rs_score=score_res.rs_score,
                    vol_score=score_res.vol_score,
                    trend_score=score_res.trend_score,
                    liq_score=score_res.liq_score,
                    ema20_1h=score_res.ema20_1h,
                    ema50_1h=score_res.ema50_1h,
                    daily_ema20=score_res.daily_ema20,
                    vol_ratio=score_res.vol_ratio,
                    rs_diff_pct=score_res.rs_diff_pct,
                    spread_bps=score_res.spread_bps,
                    quote_volume_24h=score_res.quote_volume_24h,
                    suggested_entry_low=score_res.suggested_entry_low,
                    suggested_entry_high=score_res.suggested_entry_high,
                    suggested_stop=score_res.suggested_stop,
                    telegram_sent=alert_sent,
                    metrics={
                        "alt_ret_6h": score_res.alt_return_6h_pct,
                        "btc_ret_6h": score_res.btc_return_6h_pct,
                        "risk_to_stop_pct": score_res.risk_to_stop_pct,
                    },
                )

                print(f"🚨 [ALERTED #{alert_id}] {symbol} Stage 1 setup recorded and dispatched!")
                alerted_results.append(score_res)

        elapsed = time.time() - start_time
        print("\n" + "─" * 70)
        print(f"🏁 SCAN CYCLE SUMMARY ({elapsed:.1f}s)")
        print(f"• Total Filtered Pairs Checked: {total_tickers}")
        print(f"• Failed Hard Gates / Inactive: {gated_count}")
        print(f"• Scored Candidates (≥ {self.config.min_log_score}): {scored_count}")
        print(f"• New Stage 1 Alerts Dispatched: {len(alerted_results)}")
        print("═" * 70 + "\n")

        return alerted_results
