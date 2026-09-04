"""
Performance Tracker module for MEXC Quiet Accumulation Scanner.
Evaluates the forward price performance of historical alerts (5m, 15m, 1h, 4h, 24h returns, MFE, MAE)
and generates comparative analytics.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import pandas as pd
from tabulate import tabulate

from config import ScannerConfig, load_config
from database import Database
from mexc_client import MexcClient


class PerformanceTracker:
    def __init__(self, db: Optional[Database] = None, client: Optional[MexcClient] = None):
        self.db = db or Database()
        self.client = client or MexcClient()

    def evaluate_all_pending_alerts(self) -> int:
        """
        Evaluate all incomplete alerts in the database by fetching recent candle data.
        Returns number of evaluated alerts.
        """
        pending_alerts = self.db.get_pending_performance_alerts()
        if not pending_alerts:
            return 0

        print(f"[PERF] Found {len(pending_alerts)} alerts pending performance tracking.")
        evaluated_count = 0

        for alert in pending_alerts:
            self.evaluate_single_alert(alert)
            evaluated_count += 1

        return evaluated_count

    def evaluate_single_alert(self, alert: Dict[str, Any]) -> None:
        """
        Evaluate subsequent forward returns for a single alert.
        Fetches 5m, 15m, and 1h candles since alert_timestamp_unix.
        """
        alert_id = alert["alert_id"]
        symbol = alert["symbol"]
        alert_unix_ms = alert["alert_timestamp_unix"] * 1000
        alert_price = alert["alert_price"]

        now_unix_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        elapsed_seconds = (now_unix_ms - alert_unix_ms) / 1000

        price_5m = alert.get("price_5m")
        return_5m_pct = alert.get("return_5m_pct")
        price_15m = alert.get("price_15m")
        return_15m_pct = alert.get("return_15m_pct")
        price_1h = alert.get("price_1h")
        return_1h_pct = alert.get("return_1h_pct")
        price_4h = alert.get("price_4h")
        return_4h_pct = alert.get("return_4h_pct")
        price_24h = alert.get("price_24h")
        return_24h_pct = alert.get("return_24h_pct")
        mfe_pct = alert.get("max_favorable_excursion_pct")
        mae_pct = alert.get("max_adverse_excursion_pct")

        # Fetch 5m candles to evaluate 5m, 15m, and excursion
        df_5m = self.client.fetch_ohlcv_df(symbol, timeframe="5m", limit=300)

        if df_5m is not None and len(df_5m) > 0:
            # Filter candles that closed at or after alert time
            df_post = df_5m[df_5m["timestamp"] >= alert_unix_ms].copy()

            if len(df_post) >= 1 and price_5m is None:
                # 1st 5m candle close after alert
                price_5m = float(df_post["close"].iloc[0])
                return_5m_pct = ((price_5m - alert_price) / alert_price) * 100.0

            if len(df_post) >= 3 and price_15m is None:
                # 3rd 5m candle close (~15m)
                price_15m = float(df_post["close"].iloc[2])
                return_15m_pct = ((price_15m - alert_price) / alert_price) * 100.0

            if len(df_post) > 0:
                highest_price = float(df_post["high"].max())
                lowest_price = float(df_post["low"].min())
                mfe_pct = ((highest_price - alert_price) / alert_price) * 100.0
                mae_pct = ((lowest_price - alert_price) / alert_price) * 100.0

        # Fetch 1h candles to evaluate 1h, 4h, 24h
        if elapsed_seconds >= 3600:
            df_1h = self.client.fetch_ohlcv_df(symbol, timeframe="1h", limit=100)
            if df_1h is not None and len(df_1h) > 0:
                df_post_1h = df_1h[df_1h["timestamp"] >= alert_unix_ms].copy()

                if len(df_post_1h) >= 1 and price_1h is None:
                    price_1h = float(df_post_1h["close"].iloc[0])
                    return_1h_pct = ((price_1h - alert_price) / alert_price) * 100.0

                if len(df_post_1h) >= 4 and price_4h is None:
                    price_4h = float(df_post_1h["close"].iloc[3])
                    return_4h_pct = ((price_4h - alert_price) / alert_price) * 100.0

                if len(df_post_1h) >= 24 and price_24h is None:
                    price_24h = float(df_post_1h["close"].iloc[23])
                    return_24h_pct = ((price_24h - alert_price) / alert_price) * 100.0

        is_complete = bool(elapsed_seconds >= 86400 and price_24h is not None)

        self.db.update_performance_record(
            alert_id=alert_id,
            price_5m=price_5m,
            return_5m_pct=return_5m_pct,
            price_15m=price_15m,
            return_15m_pct=return_15m_pct,
            price_1h=price_1h,
            return_1h_pct=return_1h_pct,
            price_4h=price_4h,
            return_4h_pct=return_4h_pct,
            price_24h=price_24h,
            return_24h_pct=return_24h_pct,
            max_favorable_excursion_pct=mfe_pct,
            max_adverse_excursion_pct=mae_pct,
            is_complete=is_complete,
        )

    def print_performance_summary(self, export_csv: Optional[str] = None) -> None:
        """Fetch all performance records and print a rich comparative table."""
        records = self.db.get_all_performance_records()
        if not records:
            print("\n[PERF] No alert performance records found yet in database.")
            return

        table_rows = []
        returns_5m = []
        returns_15m = []
        returns_1h = []
        returns_4h = []
        returns_24h = []
        mfes = []
        maes = []

        for r in records:
            r5m = f"{r['return_5m_pct']:+.2f}%" if r["return_5m_pct"] is not None else "-"
            r15m = f"{r['return_15m_pct']:+.2f}%" if r["return_15m_pct"] is not None else "-"
            r1h = f"{r['return_1h_pct']:+.2f}%" if r["return_1h_pct"] is not None else "-"
            r4h = f"{r['return_4h_pct']:+.2f}%" if r["return_4h_pct"] is not None else "-"
            r24h = f"{r['return_24h_pct']:+.2f}%" if r["return_24h_pct"] is not None else "-"
            mfe = f"{r['max_favorable_excursion_pct']:+.2f}%" if r["max_favorable_excursion_pct"] is not None else "-"
            mae = f"{r['max_adverse_excursion_pct']:+.2f}%" if r["max_adverse_excursion_pct"] is not None else "-"

            if r["return_5m_pct"] is not None:
                returns_5m.append(r["return_5m_pct"])
            if r["return_15m_pct"] is not None:
                returns_15m.append(r["return_15m_pct"])
            if r["return_1h_pct"] is not None:
                returns_1h.append(r["return_1h_pct"])
            if r["return_4h_pct"] is not None:
                returns_4h.append(r["return_4h_pct"])
            if r["return_24h_pct"] is not None:
                returns_24h.append(r["return_24h_pct"])
            if r["max_favorable_excursion_pct"] is not None:
                mfes.append(r["max_favorable_excursion_pct"])
            if r["max_adverse_excursion_pct"] is not None:
                maes.append(r["max_adverse_excursion_pct"])

            # Format price string
            price_val = r["alert_price"]
            p_str = f"${price_val:,.4f}" if price_val >= 1.0 else f"${price_val:.6f}"

            table_rows.append([
                r["alert_id"],
                r["alert_timestamp"][:19].replace("T", " "),
                r["symbol"],
                p_str,
                f"{r['final_score']:.2f}",
                r5m,
                r15m,
                r1h,
                r4h,
                r24h,
                mfe,
                mae,
            ])

        headers = [
            "ID", "Alert Time (UTC)", "Symbol", "Alert Px", "Score",
            "5m Ret", "15m Ret", "1h Ret", "4h Ret", "24h Ret", "Max MFE", "Max MAE"
        ]

        print("\n" + "=" * 90)
        print("📊 HISTORICAL ALERT SUBSEQUENT PERFORMANCE MATRIX")
        print("=" * 90)
        print(tabulate(table_rows, headers=headers, tablefmt="grid"))

        # Aggregate Statistics
        total_alerts = len(records)
        print("\n" + "─" * 50)
        print("📈 AGGREGATE PERFORMANCE METRICS")
        print("─" * 50)
        print(f"• Total Logged Alerts: {total_alerts}")

        def _calc_stats(arr: List[float], label: str):
            if not arr:
                print(f"• {label}: No data yet")
                return
            avg = sum(arr) / len(arr)
            win_rate = (len([x for x in arr if x > 0]) / len(arr)) * 100.0
            print(f"• {label}: Avg = {avg:+.2f}% | Win Rate (>0%) = {win_rate:.1f}% (n={len(arr)})")

        _calc_stats(returns_5m, "5m Horizon")
        _calc_stats(returns_15m, "15m Horizon")
        _calc_stats(returns_1h, "1h Horizon")
        _calc_stats(returns_4h, "4h Horizon")
        _calc_stats(returns_24h, "24h Horizon")

        if mfes:
            avg_mfe = sum(mfes) / len(mfes)
            print(f"• Avg Max Favorable Excursion (Upside Spike): +{avg_mfe:.2f}%")
        if maes:
            avg_mae = sum(maes) / len(maes)
            print(f"• Avg Max Adverse Excursion (Drawdown): {avg_mae:.2f}%")
        print("─" * 50 + "\n")

        if export_csv:
            df = pd.DataFrame(records)
            df.to_csv(export_csv, index=False)
            print(f"[EXPORT] Saved full performance records to {export_csv}")


def main():
    parser = argparse.ArgumentParser(description="MEXC Accumulation Scanner Performance Tracker")
    parser.add_argument("--config", type=str, default="config.json", help="Path to config file")
    parser.add_argument("--evaluate", action="store_true", default=True, help="Fetch latest prices for pending alerts")
    parser.add_argument("--export-csv", type=str, default=None, help="Export results to CSV file")
    args = parser.parse_args()

    cfg = load_config(args.config)
    db = Database(cfg.database_path)
    client = MexcClient(cfg.request_delay_seconds)

    tracker = PerformanceTracker(db=db, client=client)

    if args.evaluate:
        tracker.evaluate_all_pending_alerts()

    tracker.print_performance_summary(export_csv=args.export_csv)


if __name__ == "__main__":
    main()
