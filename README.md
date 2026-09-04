# MEXC Quiet Accumulation Scanner (Stage 1) with Telegram Alerts

A production-ready Python application that continuously scans MEXC Spot USDT altcoin pairs for **Quiet Accumulation (Stage 1)** setups, evaluates hard gates and multi-factor accumulation scores, logs candidates and alerts to a local SQLite database, dispatches structured Telegram notifications with cooldown management, and provides tools to verify subsequent price performance (**5m, 15m, 1h, 4h, 24h returns**).

---

## 🚀 Key Features

- **Public REST API via CCXT**: Uses MEXC Spot REST API with automatic rate limiting and robust error handling. No API keys required for public scanning.
- **Strict Hard Gates**:
  - Minimum 24h quote volume $\ge \$250,000$ (configurable)
  - Order-book spread $\le 80\text{ bps}$ ($0.80\%$)
  - At least 100 historical 1h candles
  - Price not overextended ($> 12\%$ above 1h EMA20)
  - Daily trend filter (price not $> 5\%$ below daily EMA20)
- **Multi-Factor Stage 1 Accumulation Scoring** (Weights sum to 1.0):
  - **Relative Strength vs BTC (0.40)**: 6h outperformance $\Delta\text{Alt}_{6\text{h}} - \Delta\text{BTC}_{6\text{h}}$.
  - **Volume Acceleration (0.30)**: Gradual ramp ($1.2\times - 3.0\times$ recent 3h vs prior 15h base); penalizes extreme spikes ($> 5.0\times$) to prevent pump-and-dump chasing.
  - **Trend Structure (0.25)**: Price $\ge$ EMA20, EMA20 $\ge$ EMA50, and EMA20 sloping upward.
  - **Liquidity / Spread (0.05)**: Tighter spread receives higher baseline score.
- **Telegram Alerts**:
  - High-conviction alerts (Score $\ge 0.65$) formatted in clean Markdown.
  - Includes suggested entry zone, conservative stop-loss, factor breakdown, and MEXC chart link.
  - Per-symbol cooldown (default: 180 minutes) to avoid repeated notifications.
  - Supports regular chats, groups, and supergroup Topics (`thread_id`).
- **Research & Forward Performance Tracker**:
  - Persists all candidate evaluations and alerts to SQLite (`scanner_data.db`).
  - Standalone performance script (`performance_tracker.py`) calculates 5m, 15m, 1h, 4h, 24h forward returns, Max Favorable Excursion (MFE), and Max Adverse Excursion (MAE).

---

## 📂 Project Structure

```
mexc-accumulation-scanner/
├── config.py                 # Configuration loader (supports .env and config.json)
├── config.example.json       # JSON configuration template
├── .env.example              # Environment variables template
├── database.py               # SQLite logger for candidates, alerts, and performance
├── scoring.py                # Hard Gates & Stage 1 Accumulation scoring engine
├── mexc_client.py            # MEXC REST client using CCXT
├── telegram_alerts.py        # Telegram alert formatter and dispatcher
├── performance_tracker.py    # Analytics tool for measuring forward price performance
├── scanner.py                # Continuous scan cycle orchestrator
├── main.py                   # CLI entrypoint
├── test_scanner.py           # Unit test suite
├── requirements.txt          # Python dependencies
└── README.md                 # Documentation
```

---

## 🛠️ Installation & Setup

### 1. Requirements
- Python 3.10+ (tested on Python 3.11/3.12)
- Recommended workspace directory: `C:\Users\phkim\.gemini\antigravity-ide\scratch\mexc-accumulation-scanner`

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Telegram Bot Setup
1. Open Telegram and message [@BotFather](https://t.me/BotFather).
2. Send `/newbot` and follow the instructions to create your bot and copy the **Bot Token** (e.g. `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`).
3. To get your **Chat ID**:
   - Send a message to your bot or add your bot to your alert group/channel.
   - Message [@userinfobot](https://t.me/userinfobot) or [@RawDataBot](https://t.me/RawDataBot) to get your Chat ID (e.g., `123456789` or `-1001234567890` for groups).
   - If using a Forum/Topic supergroup, copy the Topic ID as `thread_id`.

### 4. Configuration
Create a `config.json` file in the project folder (or copy `config.example.json`):

```json
{
  "scan_interval_seconds": 300,
  "cooldown_minutes": 180,
  "min_alert_score": 0.65,
  "min_log_score": 0.45,
  "database_path": "scanner_data.db",
  "telegram": {
    "bot_token": "YOUR_TELEGRAM_BOT_TOKEN_HERE",
    "chat_id": "YOUR_TELEGRAM_CHAT_ID_HERE",
    "thread_id": null,
    "enabled": true,
    "send_chart_link": true
  },
  "gates": {
    "min_24h_quote_volume": 250000,
    "max_spread_bps": 80,
    "min_1h_candles": 100,
    "max_ema20_1h_extension_pct": 0.12,
    "max_daily_bearish_pct": -0.05
  },
  "weights": {
    "weight_rs": 0.40,
    "weight_volume": 0.30,
    "weight_trend": 0.25,
    "weight_liquidity": 0.05
  }
}
```

*Alternatively, you can set environment variables in a `.env` file.*

---

## 🚦 Running the Scanner

### 1. Dry-Run / Console Mode (No Telegram credentials needed)
Runs the scanner without sending live Telegram messages and prints all candidate logs and formatted alerts directly in your console:
```bash
python main.py --dry-run
```

### 2. Single Scan Cycle Check
Runs one full scan cycle across all active MEXC Spot pairs and exits:
```bash
python main.py --once
```

### 3. Production Continuous Daemon
Runs continuously every 5 minutes (300 seconds):
```bash
python main.py
```

### 4. Custom Scan Interval (e.g., 2 minutes)
```bash
python main.py --interval 120
```

---

## 📱 Sample Telegram Alert Message

```markdown
🚨 STAGE 1 ALERT: QUIET ACCUMULATION
━━━━━━━━━━━━━━━━━━━━━━
🪙 Asset: KAS/USDT
💵 Price: $0.1482
⭐️ Accumulation Score: 0.78 / 1.00
🏷 Phase: Stage 1 (Quiet Accumulation)
━━━━━━━━━━━━━━━━━━━━━━
📊 Factor Breakdown:
• Relative Strength (6h): 0.85 (Alt: +4.20% vs BTC: +0.80% | Diff: +3.40%)
• Volume Ramp: 0.82 (1.75x vs 15h base)
• Trend Alignment: 0.70 (1h EMA20: $0.1460 | EMA50: $0.1435)
• Liquidity / Spread: 0.88 (9.5 bps | Vol: $1,450,200)
━━━━━━━━━━━━━━━━━━━━━━
🎯 Suggested Entry Zone: $0.1460 – $0.1482
🛑 Conservative Stop: $0.1420 (-4.18% risk)
🔗 Trade on MEXC Spot
━━━━━━━━━━━━━━━━━━━━━━
🔬 Research & Signal Tracking Only. Not Financial Advice.
```

---

## 📊 Historical Performance & Forward Return Tracking

The application logs every alert and candidate into SQLite (`scanner_data.db`).

You can evaluate the subsequent performance of all alerts across multiple time horizons (**5m, 15m, 1h, 4h, 24h**) and measure maximum upside (MFE) vs maximum drawdown (MAE):

### Run Performance Tracker:
```bash
python performance_tracker.py
```
Or via main:
```bash
python main.py --eval-perf
```

### Export Performance Data to CSV:
```bash
python performance_tracker.py --export-csv alert_performance_results.csv
```

### Output Matrix Sample:
```
+----+---------------------+-----------+------------+---------+----------+-----------+----------+----------+-----------+-----------+-----------+
| ID | Alert Time (UTC)    | Symbol    | Alert Px   | Score   | 5m Ret   | 15m Ret   | 1h Ret   | 4h Ret   | 24h Ret   | Max MFE   | Max MAE   |
+----+---------------------+-----------+------------+---------+----------+-----------+----------+----------+-----------+-----------+-----------+
|  1 | 2026-09-03 20:00:00 | KAS/USDT  | $0.1482    | 0.78    | +0.45%   | +1.10%    | +2.40%   | +5.15%   | +8.20%    | +9.10%    | -1.05%    |
+----+---------------------+-----------+------------+---------+----------+-----------+----------+----------+-----------+-----------+-----------+

--------------------------------------------------
📈 AGGREGATE PERFORMANCE METRICS
--------------------------------------------------
• Total Logged Alerts: 1
• 5m Horizon: Avg = +0.45% | Win Rate (>0%) = 100.0%
• 15m Horizon: Avg = +1.10% | Win Rate (>0%) = 100.0%
• 1h Horizon: Avg = +2.40% | Win Rate (>0%) = 100.0%
• 4h Horizon: Avg = +5.15% | Win Rate (>0%) = 100.0%
• 24h Horizon: Avg = +8.20% | Win Rate (>0%) = 100.0%
• Avg Max Favorable Excursion (Upside Spike): +9.10%
• Avg Max Adverse Excursion (Drawdown): -1.05%
```

---

## 🧪 Running Unit Tests

To run the full unit test suite:
```bash
python test_scanner.py
```

To run a live MEXC API connectivity test:
```bash
python test_live_mexc.py
```
