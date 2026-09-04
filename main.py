"""
Main CLI entrypoint for MEXC Quiet Accumulation Scanner.
Runs continuous scan daemon or one-off verification cycles.
"""

from __future__ import annotations

import argparse
import signal
import sys
import time

from config import load_config
from database import Database
from mexc_client import MexcClient
from performance_tracker import PerformanceTracker
from scanner import AccumulationScanner
from telegram_alerts import TelegramAlertManager


def main():
    parser = argparse.ArgumentParser(
        description="MEXC Quiet Accumulation Scanner (Stage 1 Setup Detector with Telegram Alerts)"
    )
    parser.add_argument(
        "--config",
        type=str,
        default="config.json",
        help="Path to configuration JSON file (default: config.json)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single scan cycle and exit immediately",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run in dry-run mode (suppress live Telegram messages, log alerts to console)",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=None,
        help="Override scan interval in seconds (default: from config, usually 300)",
    )
    parser.add_argument(
        "--eval-perf",
        action="store_true",
        help="Evaluate performance of historical alerts and print matrix",
    )
    args = parser.parse_args()

    # Load configuration
    config = load_config(args.config)

    if args.interval:
        config.scan_interval_seconds = args.interval

    if args.dry_run:
        config.telegram.enabled = False
        print("[CONFIG] Dry-Run mode enabled: Live Telegram messaging disabled.")

    # Initialize components
    db = Database(config.database_path)
    client = MexcClient(request_delay_seconds=config.request_delay_seconds)
    telegram_mgr = TelegramAlertManager(config.telegram, db, config.cooldown_minutes)

    if args.eval_perf:
        print("[INFO] Running performance evaluation on historical alerts...")
        tracker = PerformanceTracker(db=db, client=client)
        tracker.evaluate_all_pending_alerts()
        tracker.print_performance_summary()
        sys.exit(0)

    scanner = AccumulationScanner(
        config=config,
        db=db,
        client=client,
        telegram=telegram_mgr,
    )

    print("\n" + "█" * 70)
    print("█  MEXC SPOT QUIET ACCUMULATION SCANNER (STAGE 1)")
    print("█  Production Signal Generation & Telegram Alert Daemon")
    print("█" * 70)
    print(f"• Database: {config.database_path}")
    print(f"• Scan Interval: {config.scan_interval_seconds}s ({(config.scan_interval_seconds/60):.1f} mins)")
    print(f"• Alert Threshold: Score ≥ {config.min_alert_score}")
    print(f"• Cooldown Period: {config.cooldown_minutes} minutes")
    print(f"• Telegram Active: {'YES' if telegram_mgr.is_configured() else 'NO (Dry-run / Console only)'}")
    print("█" * 70 + "\n")

    # Graceful shutdown handler
    running = True

    def sigint_handler(sig, frame):
        nonlocal running
        print("\n[SHUTDOWN] Received termination signal. Exiting gracefully after current task...")
        running = False

    signal.signal(signal.SIGINT, sigint_handler)
    signal.signal(signal.SIGTERM, sigint_handler)

    try:
        while running:
            # Run scan cycle
            scanner.scan_cycle()

            if args.once:
                print("[INFO] Single scan cycle complete (--once). Exiting.")
                break

            # Sleep until next scan interval
            interval = config.scan_interval_seconds
            print(f"[SLEEP] Waiting {interval} seconds until next scan cycle... (Press Ctrl+C to stop)")

            # Sleep in 1-second chunks to allow prompt SIGINT handling
            for _ in range(interval):
                if not running:
                    break
                time.sleep(1)

    except KeyboardInterrupt:
        print("\n[STOPPED] Scanner stopped by user.")


if __name__ == "__main__":
    main()
