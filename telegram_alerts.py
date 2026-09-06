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

    def format_alert_message_html(self, result: ScoringResult, weex_outcome: Optional[Any] = None) -> str:
        """Format a clean, structured HTML message for the Stage 1 Accumulation alert."""
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
        mexc_link = f"https://www.mexc.com/exchange/{base_asset}_USDT"

        weex_status_section = ""
        if weex_outcome:
            notional_val = getattr(weex_outcome, "notional_usd", 0.0)
            notional_str = f" (~${notional_val:.2f} USD)" if notional_val > 0 else ""
            if getattr(weex_outcome, "status", None) == "EXECUTED":
                weex_status_section = (
                    f"🏛 <b>WEEX:</b> ✅ <code>LONG {weex_outcome.weex_symbol}</code> "
                    f"(Qty: {weex_outcome.quantity}{notional_str} | SL: ${weex_outcome.stop_loss:.4f} | TP: ${weex_outcome.take_profit:.4f})\n"
                )
            elif getattr(weex_outcome, "status", None) == "SIMULATED":
                weex_status_section = (
                    f"🏛 <b>WEEX:</b> 🧪 <code>Simulated LONG {weex_outcome.weex_symbol}</code> "
                    f"({weex_outcome.leverage}x | Qty: {weex_outcome.quantity}{notional_str})\n"
                )
            elif getattr(weex_outcome, "status", None) == "UNLISTED":
                weex_status_section = "🏛 <b>WEEX:</b> ⚠️ <i>Not Listed on WEEX Contracts (Skipped)</i>\n"
            elif getattr(weex_outcome, "status", None) == "FAILED":
                clean_err = html.escape(str(getattr(weex_outcome, 'message', 'Failed'))[:60])
                weex_status_section = f"🏛 <b>WEEX:</b> ❌ <i>Order Failed: {clean_err}</i>\n"

        msg = (
            f"🚨 <b>STAGE 1 ALERT: QUIET ACCUMULATION</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🪙 <b>Asset:</b> <code>{html.escape(clean_symbol)}</code>\n"
            f"💵 <b>Price:</b> <code>{price_fmt}</code>\n"
            f"⭐️ <b>Accumulation Score:</b> <code>{result.final_score:.2f} / 1.00</code>\n"
            f"🏷 <b>Phase:</b> <code>{html.escape(result.stage)}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 <b>Factor Breakdown:</b>\n"
            f"• <b>Relative Strength (6h):</b> <code>{result.rs_score:.2f}</code> (Alt: {result.alt_return_6h_pct:+.2f}% vs BTC: {result.btc_return_6h_pct:+.2f}% | Diff: {result.rs_diff_pct:+.2f}%)\n"
            f"• <b>Volume Ramp:</b> <code>{result.vol_score:.2f}</code> ({result.vol_ratio:.2f}x vs 15h base)\n"
            f"• <b>Trend Alignment:</b> <code>{result.trend_score:.2f}</code> (1h EMA20: {ema20_fmt} | EMA50: {ema50_fmt})\n"
            f"• <b>Liquidity / Spread:</b> <code>{result.liq_score:.2f}</code> ({result.spread_bps:.1f} bps | Vol: ${result.quote_volume_24h:,.0f})\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎯 <b>Suggested Entry Zone:</b> <code>{entry_low_fmt} – {entry_high_fmt}</code>\n"
            f"🛑 <b>Conservative Stop:</b> <code>{stop_fmt}</code> (-{result.risk_to_stop_pct:.2f}% risk)\n"
            f"{weex_status_section}"
            f"🔗 <a href=\"{mexc_link}\">Trade on MEXC Spot</a>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔬 <i>Research & Signal Tracking Only. Not Financial Advice.</i>"
        )
        return msg

    def format_alert_message(self, result: ScoringResult, weex_outcome: Optional[Any] = None) -> str:
        """Alias for backward compatibility."""
        return self.format_alert_message_html(result, weex_outcome)

    def send_test_message(self, text: Optional[str] = None) -> bool:
        """Send an immediate test ping message to verify Telegram setup."""
        if not self.is_configured():
            print("[ERROR] Telegram bot_token or chat_id is missing/empty in configuration.")
            return False

        body = text or (
            "🔔 <b>MEXC Accumulation Scanner Test</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "✅ Telegram notifications successfully connected!\n"
            "Bot is active and monitoring MEXC Spot USDT pairs."
        )

        url = f"https://api.telegram.org/bot{self.config.bot_token}/sendMessage"
        payload = {
            "chat_id": self.config.chat_id,
            "text": body,
            "parse_mode": "HTML",
        }
        if self.config.thread_id is not None:
            payload["message_thread_id"] = self.config.thread_id

        try:
            resp = requests.post(url, json=payload, timeout=10)
            data = resp.json()
            if data.get("ok"):
                print("[SUCCESS] Telegram test message sent successfully!")
                return True
            else:
                print(f"[ERROR] Telegram API Error: {data.get('description')} (Error code: {data.get('error_code')})")
                return False
        except Exception as e:
            print(f"[ERROR] HTTP request failed when connecting to Telegram: {e}")
            return False

    def send_alert(self, result: ScoringResult, weex_outcome: Optional[Any] = None) -> bool:
        """
        Send Telegram notification if configured and not on cooldown.
        Returns True if sent or handled in dry-run mode.
        """
        if not self.can_send_alert(result.symbol):
            print(f"[COOLDOWN] {result.symbol} is currently cooling down ({self.cooldown_minutes}m). Skipping alert.")
            return False

        message_html = self.format_alert_message_html(result, weex_outcome)

        if not self.is_configured():
            print("\n[TELEGRAM DRY-RUN / CONSOLE ALERT]")
            print(message_html)
            print("-" * 50)
            return True

        url = f"https://api.telegram.org/bot{self.config.bot_token}/sendMessage"
        payload = {
            "chat_id": self.config.chat_id,
            "text": message_html,
            "parse_mode": "HTML",
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
                print(f"[WARN] Telegram HTML send failed: {data.get('description')}. Retrying as plain text...")
                # Fallback to plain text if HTML formatting failed
                payload["parse_mode"] = None
                resp_plain = requests.post(url, json=payload, timeout=10)
                if resp_plain.json().get("ok"):
                    print(f"[TELEGRAM SENT] Alert sent as plain text for {result.symbol}")
                    return True
                else:
                    print(f"[ERROR] Telegram plain text send also failed: {resp_plain.json().get('description')}")
                    return False
        except Exception as e:
            print(f"[ERROR] Failed to dispatch Telegram alert for {result.symbol}: {e}")
            return False
