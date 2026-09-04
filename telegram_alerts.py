"""
Telegram Alerts module for MEXC Quiet Accumulation Scanner.
Formats structured Markdown alerts and sends them via Telegram Bot API with
per-symbol cooldown management and thread/topic support.
"""

from __future__ import annotations

import html
from typing import Optional
import requests

from config import TelegramConfig
from database import Database
from scoring import ScoringResult


class TelegramAlertManager:
    def __init__(self, config: TelegramConfig, db: Database, cooldown_minutes: int = 180):
        self.config = config
        self.db = db
        self.cooldown_minutes = cooldown_minutes

    def is_configured(self) -> bool:
        """Check if Telegram bot credentials are provided and enabled."""
        return (
            self.config.enabled
            and bool(self.config.bot_token)
            and bool(self.config.chat_id)
            and self.config.bot_token != "YOUR_TELEGRAM_BOT_TOKEN_HERE"
        )

    def can_send_alert(self, symbol: str) -> bool:
        """Check whether the symbol is allowed to trigger an alert (cooldown check)."""
        return not self.db.is_on_cooldown(symbol, self.cooldown_minutes)

    def format_alert_message(self, result: ScoringResult) -> str:
        """Format a clean, structured Markdown message for the Stage 1 Accumulation alert."""
        # Format numbers with appropriate precision
        if result.price >= 1.0:
            price_fmt = f"${result.price:,.4f}"
            entry_low_fmt = f"${result.suggested_entry_low:,.4f}"
            entry_high_fmt = f"${result.suggested_entry_high:,.4f}"
            stop_fmt = f"${result.suggested_stop:,.4f}"
            ema20_fmt = f"${result.ema20_1h:,.4f}"
            ema50_fmt = f"${result.ema50_1h:,.4f}"
        else:
            price_fmt = f"${result.price:.6f}"
            entry_low_fmt = f"${result.suggested_entry_low:.6f}"
            entry_high_fmt = f"${result.suggested_entry_high:.6f}"
            stop_fmt = f"${result.suggested_stop:.6f}"
            ema20_fmt = f"${result.ema20_1h:.6f}"
            ema50_fmt = f"${result.ema50_1h:.6f}"

        clean_symbol = result.symbol.replace("/USDT:USDT", "/USDT")
        base_asset = clean_symbol.split("/")[0]

        # Chart link
        mexc_link = f"https://www.mexc.com/exchange/{base_asset}_USDT"

        msg = (
            f"🚨 *STAGE 1 ALERT: QUIET ACCUMULATION*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🪙 *Asset:* `{clean_symbol}`\n"
            f"💵 *Price:* `{price_fmt}`\n"
            f"⭐️ *Accumulation Score:* `{result.final_score:.2f} / 1.00`\n"
            f"🏷 *Phase:* `{result.stage}`\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 *Factor Breakdown:*\n"
            f"• *Relative Strength (6h):* `{result.rs_score:.2f}` (Alt: `{result.alt_return_6h_pct:+.2f}%` vs BTC: `{result.btc_return_6h_pct:+.2f}%` | Diff: `{result.rs_diff_pct:+.2f}%`)\n"
            f"• *Volume Ramp:* `{result.vol_score:.2f}` (`{result.vol_ratio:.2f}x` vs 15h base)\n"
            f"• *Trend Alignment:* `{result.trend_score:.2f}` (1h EMA20: `{ema20_fmt}` | EMA50: `{ema50_fmt}`)\n"
            f"• *Liquidity / Spread:* `{result.liq_score:.2f}` (`{result.spread_bps:.1f} bps` | Vol: `${result.quote_volume_24h:,.0f}`)\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎯 *Suggested Entry Zone:* `{entry_low_fmt}` – `{entry_high_fmt}`\n"
            f"🛑 *Conservative Stop:* `{stop_fmt}` (`-{result.risk_to_stop_pct:.2f}%` risk)\n"
            f"🔗 [Trade on MEXC Spot]({mexc_link})\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔬 _Research & Signal Tracking Only. Not Financial Advice._"
        )
        return msg

    def send_alert(self, result: ScoringResult) -> bool:
        """
        Send Telegram notification if configured and not on cooldown.
        Returns True if sent or handled in dry-run mode.
        """
        if not self.can_send_alert(result.symbol):
            print(f"[COOLDOWN] {result.symbol} is currently cooling down ({self.cooldown_minutes}m). Skipping alert.")
            return False

        message_text = self.format_alert_message(result)

        if not self.is_configured():
            print("\n[TELEGRAM DRY-RUN / CONSOLE ALERT]")
            print(message_text)
            print("-" * 50)
            return True

        url = f"https://api.telegram.org/bot{self.config.bot_token}/sendMessage"
        payload = {
            "chat_id": self.config.chat_id,
            "text": message_text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": not self.config.send_chart_link,
        }

        if self.config.thread_id is not None:
            payload["message_thread_id"] = self.config.thread_id

        try:
            resp = requests.post(url, json=payload, timeout=10)
            data = resp.json()
            if data.get("ok"):
                print(f"[TELEGRAM SENT] Alert sent successfully for {result.symbol}")
                return True
            else:
                print(f"[ERROR] Telegram API returned error: {data.get('description')}")
                return False
        except Exception as e:
            print(f"[ERROR] Failed to dispatch Telegram alert for {result.symbol}: {e}")
            return False
