"""
Unit and integration tests for MEXC Quiet Accumulation Scanner.
Tests Hard Gates, Scoring algorithm, Database logging, Telegram formatting,
and Performance calculation.
"""

from __future__ import annotations

import os
import unittest
import numpy as np
import pandas as pd

from config import HardGatesConfig, ScoringWeightsConfig, TelegramConfig
from database import Database
from scoring import (
    calculate_quiet_accumulation_score,
    compute_ema,
    compute_liquidity_score,
    compute_relative_strength_score,
    compute_trend_structure_score,
    compute_volume_acceleration_score,
    evaluate_hard_gates,
)
from telegram_alerts import TelegramAlertManager


def generate_mock_ohlcv(
    num_candles: int = 120,
    base_price: float = 10.0,
    trend_type: str = "bullish_consolidation",
    vol_multiplier_recent: float = 1.8,
) -> pd.DataFrame:
    """Generate synthetic OHLCV data for testing."""
    np.random.seed(42)
    timestamps = [1700000000000 + i * 3600000 for i in range(num_candles)]

    closes = [base_price]
    for i in range(1, num_candles):
        if trend_type == "bullish_consolidation":
            # Gentle drift up with tight consolidation
            ret = 0.001 + np.random.normal(0, 0.005)
        elif trend_type == "overextended":
            # Massive pump in the last 5 candles
            if i >= num_candles - 5:
                ret = 0.05
            else:
                ret = 0.001
        elif trend_type == "downtrend":
            ret = -0.005 + np.random.normal(0, 0.005)
        else:
            ret = np.random.normal(0, 0.01)

        closes.append(max(0.0001, closes[-1] * (1.0 + ret)))

    closes = np.array(closes)
    highs = closes * (1.0 + np.random.uniform(0.002, 0.01, size=num_candles))
    lows = closes * (1.0 - np.random.uniform(0.002, 0.01, size=num_candles))
    opens = (closes + np.roll(closes, 1)) / 2.0
    opens[0] = closes[0]

    # Volumes
    volumes = np.random.uniform(1000, 2000, size=num_candles)
    # Apply recent volume multiplier to last 3 candles
    volumes[-3:] = volumes[-3:] * vol_multiplier_recent

    df = pd.DataFrame({
        "timestamp": timestamps,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
    })
    return df


class TestScannerScoring(unittest.TestCase):
    def setUp(self):
        self.gates = HardGatesConfig()
        self.weights = ScoringWeightsConfig()
        self.df_1h_normal = generate_mock_ohlcv(120, 10.0, "bullish_consolidation", 1.8)
        self.df_btc_1h = generate_mock_ohlcv(120, 50000.0, "bullish_consolidation", 1.0)
        self.df_1d = generate_mock_ohlcv(30, 10.0, "bullish_consolidation", 1.0)

    def test_hard_gates_pass(self):
        result = evaluate_hard_gates(
            df_1h=self.df_1h_normal,
            df_1d=self.df_1d,
            quote_volume_24h=500000.0,
            spread_bps=30.0,
            gates=self.gates,
        )
        self.assertTrue(result.passed, f"Gate check failed unexpectedly: {result.reason}")

    def test_hard_gates_volume_rejection(self):
        result = evaluate_hard_gates(
            df_1h=self.df_1h_normal,
            df_1d=self.df_1d,
            quote_volume_24h=50000.0,  # Below $100k threshold
            spread_bps=30.0,
            gates=self.gates,
        )
        self.assertFalse(result.passed)
        self.assertIn("Low 24h quote volume", result.reason)

    def test_hard_gates_spread_rejection(self):
        result = evaluate_hard_gates(
            df_1h=self.df_1h_normal,
            df_1d=self.df_1d,
            quote_volume_24h=500000.0,
            spread_bps=120.0,  # Above 80 bps
            gates=self.gates,
        )
        self.assertFalse(result.passed)
        self.assertIn("Wide spread", result.reason)

    def test_hard_gates_overextension_rejection(self):
        df_extended = generate_mock_ohlcv(120, 10.0, "overextended", 1.5)
        result = evaluate_hard_gates(
            df_1h=df_extended,
            df_1d=self.df_1d,
            quote_volume_24h=500000.0,
            spread_bps=20.0,
            gates=self.gates,
        )
        self.assertFalse(result.passed)
        self.assertIn("Overextended", result.reason)

    def test_relative_strength_score(self):
        # Alt outperforms BTC
        rs_score, alt_ret, btc_ret, diff = compute_relative_strength_score(
            self.df_1h_normal, self.df_btc_1h
        )
        self.assertGreaterEqual(rs_score, 0.0)
        self.assertLessEqual(rs_score, 1.0)

    def test_volume_acceleration_sweet_spot_vs_extreme(self):
        df_sweet_spot = generate_mock_ohlcv(120, 10.0, "bullish_consolidation", 2.0)
        score_sweet, ratio_sweet = compute_volume_acceleration_score(df_sweet_spot)
        self.assertGreaterEqual(score_sweet, 0.75)

        # Extreme spike (>5x) should receive lower score penalty
        df_extreme = generate_mock_ohlcv(120, 10.0, "bullish_consolidation", 8.0)
        score_extreme, ratio_extreme = compute_volume_acceleration_score(df_extreme)
        self.assertLess(score_extreme, score_sweet)

    def test_trend_structure_score(self):
        score, ema20, ema50, slope = compute_trend_structure_score(self.df_1h_normal)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)

    def test_full_scoring_calculation(self):
        res = calculate_quiet_accumulation_score(
            symbol="TEST/USDT",
            df_alt_1h=self.df_1h_normal,
            df_alt_1d=self.df_1d,
            df_btc_1h=self.df_btc_1h,
            quote_volume_24h=750000.0,
            spread_bps=25.0,
            weights=self.weights,
            gates=self.gates,
        )
        self.assertEqual(res.symbol, "TEST/USDT")
        self.assertGreaterEqual(res.final_score, 0.0)
        self.assertLessEqual(res.final_score, 1.0)
        self.assertGreater(res.suggested_entry_high, 0.0)
        self.assertGreater(res.suggested_stop, 0.0)
        self.assertLess(res.suggested_stop, res.suggested_entry_high)


class TestDatabaseAndCooldown(unittest.TestCase):
    def setUp(self):
        self.db_path = "test_scanner_data.db"
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        self.db = Database(self.db_path)

    def tearDown(self):
        import gc
        gc.collect()
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except PermissionError:
                pass

    def test_save_and_retrieve_alert(self):
        alert_id = self.db.save_alert(
            symbol="ABC/USDT",
            price=1.25,
            final_score=0.78,
            stage="Stage 1 (Quiet Accumulation)",
            rs_score=0.85,
            vol_score=0.80,
            trend_score=0.75,
            liq_score=0.90,
            ema20_1h=1.20,
            ema50_1h=1.15,
            daily_ema20=1.10,
            vol_ratio=1.85,
            rs_diff_pct=3.2,
            spread_bps=15.0,
            quote_volume_24h=800000.0,
            suggested_entry_low=1.20,
            suggested_entry_high=1.25,
            suggested_stop=1.14,
            telegram_sent=True,
            metrics={"test": 123},
        )
        self.assertEqual(alert_id, 1)

        # Check cooldown
        self.assertTrue(self.db.is_on_cooldown("ABC/USDT", cooldown_minutes=180))
        self.assertFalse(self.db.is_on_cooldown("OTHER/USDT", cooldown_minutes=180))

        # Check performance tracking initialization
        pending = self.db.get_pending_performance_alerts()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["symbol"], "ABC/USDT")
        self.assertEqual(pending[0]["alert_price"], 1.25)


class TestTelegramAlertFormatting(unittest.TestCase):
    def test_message_formatting(self):
        db_path = "test_tg_db.db"
        if os.path.exists(db_path):
            os.remove(db_path)
        db = Database(db_path)
        tg = TelegramAlertManager(TelegramConfig(enabled=False), db)

        res = calculate_quiet_accumulation_score(
            symbol="PEPE/USDT",
            df_alt_1h=generate_mock_ohlcv(120, 0.000012, "bullish_consolidation", 2.2),
            df_alt_1d=generate_mock_ohlcv(30, 0.000011, "bullish_consolidation", 1.0),
            df_btc_1h=generate_mock_ohlcv(120, 60000.0, "bullish_consolidation", 1.0),
            quote_volume_24h=1200000.0,
            spread_bps=20.0,
            weights=ScoringWeightsConfig(),
            gates=HardGatesConfig(),
        )

        msg = tg.format_alert_message(res)
        self.assertIn("STAGE 1 ALERT: QUIET ACCUMULATION", msg)
        self.assertIn("PEPE/USDT", msg)
        self.assertIn("Accumulation Score", msg)
        self.assertIn("Suggested Entry Zone", msg)
        self.assertIn("Conservative Stop", msg)
        self.assertIn("Research & Signal Tracking Only", msg)

        import gc
        del tg
        del db
        gc.collect()
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except PermissionError:
                pass


if __name__ == "__main__":
    unittest.main()
