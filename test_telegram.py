"""
Diagnostic & Verification script for Telegram Alerts.
Tests bot token, chat ID, supergroup thread ID, and sends sample test notifications.
"""

from __future__ import annotations

import argparse
import sys
import requests

from config import load_config
from database import Database
from scoring import ScoringResult
from telegram_alerts import TelegramAlertManager


def main():
    parser = argparse.ArgumentParser(description="Test Telegram Alert Integration")
    parser.add_argument("--config", type=str, default="config.json", help="Path to config file")
    parser.add_argument("--token", type=str, default=None, help="Explicit Telegram Bot Token")
    parser.add_argument("--chat-id", type=str, default=None, help="Explicit Telegram Chat ID")
    parser.add_argument("--thread-id", type=int, default=None, help="Explicit Supergroup Thread/Topic ID")
    args = parser.parse_args()

    config = load_config(args.config)

    # Overrides
    if args.token:
        config.telegram.bot_token = args.token.strip().strip("'\"")
    if args.chat_id:
        config.telegram.chat_id = args.chat_id.strip().strip("'\"")
    if args.thread_id:
        config.telegram.thread_id = args.thread_id

    # Defensive cleanup on bot_token
    token = config.telegram.bot_token
    if token.lower().startswith("bot") and ":" in token:
        token = token[3:]
        config.telegram.bot_token = token

    if token and len(token) > 10 and token != "YOUR_TELEGRAM_BOT_TOKEN_HERE":
        token_display = f"{token[:6]}...{token[-4:]} (Length: {len(token)} chars)"
    elif token:
        token_display = f"[CONFIGURED - Length: {len(token)} chars]"
    else:
        token_display = "[MISSING / EMPTY]"

    print("\n" + "═" * 60)
    print("🤖 TELEGRAM BOT DIAGNOSTIC & CONNECTION CHECK")
    print("═" * 60)
    print(f"• Config File: {args.config}")
    print(f"• Bot Token:   {token_display}")
    print(f"• Chat ID:     {config.telegram.chat_id or '[MISSING]'}")
    print(f"• Thread ID:   {config.telegram.thread_id or 'None (Main Chat)'}")
    print(f"• Enabled:     {config.telegram.enabled}")
    print("─" * 60)

    if not config.telegram.bot_token or config.telegram.bot_token == "YOUR_TELEGRAM_BOT_TOKEN_HERE":
        print("\n❌ [DIAGNOSTIC FAILED] Bot token is missing or set to placeholder.")
        print("👉 Solution: Add your bot token into .env:")
        print("   TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz")
        sys.exit(1)

    if not config.telegram.chat_id or config.telegram.chat_id == "YOUR_TELEGRAM_CHAT_ID_HERE":
        print("\n❌ [DIAGNOSTIC FAILED] Chat ID is missing or set to placeholder.")
        print("👉 Solution: Set your Chat ID in .env:")
        print("   TELEGRAM_CHAT_ID=YOUR_CHAT_ID")
        sys.exit(1)

    # 1. Test getMe endpoint
    print("\n[STEP 1/3] Verifying Bot Token with Telegram API (getMe)...")
    try:
        r = requests.get(f"https://api.telegram.org/bot{config.telegram.bot_token}/getMe", timeout=10)
        data = r.json()
        if data.get("ok"):
            bot_info = data.get("result", {})
            print(f"✅ Bot Token Valid! Bot Name: @{bot_info.get('username')} ({bot_info.get('first_name')})")
        else:
            print(f"❌ Bot Token Invalid: {data.get('description')} (HTTP {r.status_code})")
            print("\n💡 Troubleshooting Tips:")
            print("1. Telegram bot tokens must look like: 1234567890:ABCdefGHIjklMNOpqrsTUVwxyz")
            print("   (Numbers before the colon, followed by ~35 letters/numbers).")
            print("2. If you copied from @BotFather, make sure no characters were missed.")
            print("3. Check if you recently revoked or regenerated this token in @BotFather.")
            print("4. You can test a token directly: python test_telegram.py --token 'YOUR_NEW_TOKEN'")
            sys.exit(1)
    except Exception as e:
        print(f"❌ Connection error reaching Telegram API: {e}")
        sys.exit(1)

    # 2. Send Test Ping
    print("\n[STEP 2/3] Sending Test Ping Message to Chat ID...")
    db = Database(config.database_path)
    tg_mgr = TelegramAlertManager(config.telegram, db, cooldown_minutes=0)
    success = tg_mgr.send_test_message()

    if not success:
        print("\n❌ [DIAGNOSTIC FAILED] Could not deliver message to the specified Chat ID.")
        print("Common causes:")
        print("1. For private chat: Have you clicked 'START' or messaged the bot first?")
        print("2. For groups/channels: Is the bot added to the group as a member/administrator?")
        print("3. Group IDs must start with '-' or '-100' (e.g. -1001234567890).")
        sys.exit(1)

    # 3. Send Sample Stage 1 Alert
    print("\n[STEP 3/3] Sending Mock Stage 1 Alert Message...")
    mock_result = ScoringResult(
        symbol="KAS/USDT",
        price=0.1482,
        final_score=0.78,
        stage="Stage 1 (Quiet Accumulation)",
        is_stage1=True,
        rs_score=0.85,
        vol_score=0.82,
        trend_score=0.70,
        liq_score=0.88,
        alt_return_6h_pct=4.20,
        btc_return_6h_pct=0.80,
        rs_diff_pct=3.40,
        vol_ratio=1.75,
        ema20_1h=0.1460,
        ema50_1h=0.1435,
        daily_ema20=0.1390,
        ema20_slope_positive=True,
        spread_bps=9.5,
        quote_volume_24h=1450200.0,
        suggested_entry_low=0.1460,
        suggested_entry_high=0.1482,
        suggested_stop=0.1420,
        risk_to_stop_pct=4.18,
    )

    alert_sent = tg_mgr.send_alert(mock_result)
    if alert_sent:
        print("\n🎉 [ALL CHECKS PASSED] Mock Stage 1 alert delivered successfully to your Telegram!")
        print("Your Telegram integration is 100% operational.")
    else:
        print("\n❌ Failed to send sample alert.")


if __name__ == "__main__":
    main()
