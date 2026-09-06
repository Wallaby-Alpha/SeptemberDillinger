"""
Unit and integration tests for WEEX symbol resolution and trade execution.
Verifies:
1. Ticker resolution and multiplier mapping (e.g. PEPE -> 1000PEPEUSDT).
2. Unlisted token handling (e.g. LIT -> None, status="UNLISTED").
3. Sizing, TP/SL calculations, and dry-run execution.
4. Telegram alert message formatting with WEEX status.
"""

import unittest
from unittest.mock import MagicMock

from config import WeexConfig, TelegramConfig
from database import Database
from scoring import ScoringResult
from telegram_alerts import TelegramAlertManager
from weex_client import WeexClient
from weex_executor import WeexTradeExecutor
from weex_resolver import WeexSymbolResolver


class TestWeexIntegration(unittest.TestCase):
    def setUp(self):
        # Create a mock WeexClient with sample market metadata
        self.mock_client = MagicMock(spec=WeexClient)
        self.mock_client.get_exchange_info.return_value = {
            "BTCUSDT": {
                "symbol": "BTCUSDT",
                "pricePrecision": 2,
                "quantityPrecision": 4,
                "contractVal": 0.0001,
                "minOrderSize": 0.0001,
                "maxLeverage": 100,
            },
            "ETHUSDT": {
                "symbol": "ETHUSDT",
                "pricePrecision": 2,
                "quantityPrecision": 3,
                "contractVal": 0.01,
                "minOrderSize": 0.01,
                "maxLeverage": 100,
            },
            "1000PEPEUSDT": {
                "symbol": "1000PEPEUSDT",
                "pricePrecision": 5,
                "quantityPrecision": 1,
                "contractVal": 1.0,
                "minOrderSize": 1.0,
                "maxLeverage": 50,
            },
            "1000BONKUSDT": {
                "symbol": "1000BONKUSDT",
                "pricePrecision": 5,
                "quantityPrecision": 1,
                "contractVal": 1.0,
                "minOrderSize": 1.0,
                "maxLeverage": 50,
            },
        }
        self.mock_client.get_available_margin.return_value = 500.0
        self.mock_client.get_mark_price.side_effect = lambda sym: {
            "BTCUSDT": 65000.0,
            "1000PEPEUSDT": 0.00985,
        }.get(sym, None)

        self.resolver = WeexSymbolResolver(self.mock_client)

        self.config = WeexConfig(
            enabled=True,
            dry_run=True,
            position_size_pct=0.10,
            leverage=3,
            take_profit_rr=2.0,
        )
        self.executor = WeexTradeExecutor(self.config, self.mock_client, self.resolver)

    def test_direct_symbol_resolution(self):
        """Test exact symbol match on WEEX."""
        resolved = self.resolver.resolve("BTC/USDT")
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.weex_symbol, "BTCUSDT")
        self.assertEqual(resolved.multiplier, 1.0)
        self.assertEqual(resolved.price_precision, 2)

    def test_multiplier_symbol_resolution(self):
        """Test meme coin multiplier resolution (e.g. PEPE -> 1000PEPEUSDT)."""
        resolved = self.resolver.resolve("PEPE/USDT")
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.weex_symbol, "1000PEPEUSDT")
        self.assertEqual(resolved.multiplier, 1000.0)
        self.assertEqual(resolved.quantity_precision, 1)

    def test_unlisted_token_safe_handling(self):
        """Verify unlisted token (like LIT) returns None and does not raise an exception."""
        resolved = self.resolver.resolve("LIT/USDT")
        self.assertIsNone(resolved)
        self.assertFalse(self.resolver.is_listed_on_weex("LIT/USDT"))

    def test_unlisted_token_trade_execution(self):
        """Verify unlisted token triggers clean UNLISTED outcome and does not crash."""
        sample_result = ScoringResult(
            symbol="LIT/USDT",
            price=0.85,
            final_score=0.75,
            stage="Stage 1: Quiet Accumulation",
            is_stage1=True,
            rs_score=0.8,
            vol_score=0.7,
            trend_score=0.8,
            liq_score=0.9,
            alt_return_6h_pct=6.0,
            btc_return_6h_pct=1.0,
            rs_diff_pct=5.0,
            vol_ratio=1.6,
            ema20_1h=0.84,
            ema50_1h=0.82,
            daily_ema20=0.80,
            ema20_slope_positive=True,
            spread_bps=15.0,
            quote_volume_24h=500000.0,
            suggested_entry_low=0.83,
            suggested_entry_high=0.86,
            suggested_stop=0.81,
            risk_to_stop_pct=4.7,
        )

        outcome = self.executor.execute_alert_signal(sample_result)
        self.assertEqual(outcome.status, "UNLISTED")
        self.assertIn("not listed on WEEX", outcome.message)

    def test_dry_run_trade_simulation(self):
        """Verify simulated dry-run order execution for listed symbol."""
        sample_result = ScoringResult(
            symbol="BTC/USDT",
            price=65000.0,
            final_score=0.82,
            stage="Stage 1: Quiet Accumulation",
            is_stage1=True,
            rs_score=0.85,
            vol_score=0.80,
            trend_score=0.85,
            liq_score=0.95,
            alt_return_6h_pct=5.0,
            btc_return_6h_pct=1.0,
            rs_diff_pct=4.0,
            vol_ratio=1.8,
            ema20_1h=64800.0,
            ema50_1h=64500.0,
            daily_ema20=64000.0,
            ema20_slope_positive=True,
            spread_bps=1.0,
            quote_volume_24h=10000000.0,
            suggested_entry_low=64800.0,
            suggested_entry_high=65200.0,
            suggested_stop=64000.0,
            risk_to_stop_pct=1.54,
        )

        outcome = self.executor.execute_alert_signal(sample_result)
        self.assertEqual(outcome.status, "SIMULATED")
        self.assertEqual(outcome.weex_symbol, "BTCUSDT")
        self.assertEqual(outcome.side, "LONG")
        self.assertGreater(outcome.quantity, 0)
        self.assertLess(outcome.stop_loss, outcome.entry_price)
        self.assertGreater(outcome.take_profit, outcome.entry_price)

    def test_telegram_message_includes_weex_status(self):
        """Verify Telegram message correctly renders WEEX execution line."""
        mock_db = MagicMock(spec=Database)
        tg_mgr = TelegramAlertManager(TelegramConfig(), mock_db)

        sample_result = ScoringResult(
            symbol="PEPE/USDT",
            price=0.00000985,
            final_score=0.78,
            stage="Stage 1: Quiet Accumulation",
            is_stage1=True,
            rs_score=0.8,
            vol_score=0.75,
            trend_score=0.8,
            liq_score=0.9,
            alt_return_6h_pct=7.0,
            btc_return_6h_pct=1.0,
            rs_diff_pct=6.0,
            vol_ratio=1.7,
            ema20_1h=0.0000097,
            ema50_1h=0.0000095,
            daily_ema20=0.0000094,
            ema20_slope_positive=True,
            spread_bps=8.0,
            quote_volume_24h=3000000.0,
            suggested_entry_low=0.0000097,
            suggested_entry_high=0.0000099,
            suggested_stop=0.0000094,
            risk_to_stop_pct=4.5,
        )

        outcome = self.executor.execute_alert_signal(sample_result)
        self.assertEqual(outcome.status, "SIMULATED")

        msg = tg_mgr.format_alert_message_html(sample_result, weex_outcome=outcome)
        self.assertIn("WEEX:", msg)
        self.assertIn("1000PEPEUSDT", msg)
        self.assertIn("Simulated LONG", msg)


if __name__ == "__main__":
    unittest.main()
