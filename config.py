"""
Configuration module for MEXC Quiet Accumulation Scanner.
Supports environment variables (.env) and JSON configuration files.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, List, Optional
from dotenv import load_dotenv


@dataclass
class TelegramConfig:
    bot_token: str = ""
    chat_id: str = ""
    thread_id: Optional[int] = None  # For Telegram supergroup topics
    enabled: bool = True
    send_chart_link: bool = True


@dataclass
class HardGatesConfig:
    min_24h_quote_volume: float = 100000.0  # Min $100k quote volume (ensures 200+ liquid pairs)
    max_spread_bps: float = 80.0            # Max 80 bps (0.80%)
    min_1h_candles: int = 100               # Min 100 candles for reliable EMA/RS
    max_ema20_1h_extension_pct: float = 0.12  # Price not > 12% above EMA20 (1h)
    max_daily_bearish_pct: float = -0.05     # Price not > 5% below daily EMA20


@dataclass
class ScoringWeightsConfig:
    weight_rs: float = 0.40          # Relative Strength vs BTC (6h)
    weight_volume: float = 0.30      # Volume Acceleration (1.2x - 3.0x ramp)
    weight_trend: float = 0.25       # Trend alignment (P > EMA20 > EMA50, slope)
    weight_liquidity: float = 0.05   # Spread tightness baseline


@dataclass
class WeexConfig:
    enabled: bool = False
    dry_run: bool = True
    api_key: str = ""
    api_secret: str = ""
    passphrase: str = ""
    base_url: str = "https://api-contract.weex.com"
    position_size_pct: float = 0.10  # 10% of available margin per trade
    fixed_order_usdt: Optional[float] = None  # If set, trades fixed USDT notional
    leverage: int = 3
    take_profit_rr: float = 2.0


@dataclass
class ScannerConfig:
    # General
    scan_interval_seconds: int = 300       # 5 minutes
    cooldown_minutes: int = 180            # 3 hours per symbol cooldown
    min_alert_score: float = 0.65          # Alert threshold
    min_log_score: float = 0.45            # Minimum score to record candidate in DB
    max_pairs: int = 200                   # Target universe size (top N coins by 24h volume)
    weex_only_universe: bool = False       # If True, only scan pairs listed on WEEX Contracts
    
    # Symbols filter
    quote_currency: str = "USDT"
    excluded_keywords: List[str] = field(
        default_factory=lambda: [
            "3L", "3S", "4L", "4S", "5L", "5S",
            "BEAR", "BULL", "DOWN", "UP",
            "USDC", "FDUSD", "TUSD", "BUSD", "DAI", "USDD", "USDE", "EUR", "TRY"
        ]
    )
    
    # Rate limiting and execution
    request_delay_seconds: float = 0.08    # Delay between API calls to respect rate limit
    max_workers: int = 5                   # Concurrency worker count for candle fetching
    
    # Database & Storage
    database_path: str = "scanner_data.db"
    
    # Components
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    gates: HardGatesConfig = field(default_factory=HardGatesConfig)
    weights: ScoringWeightsConfig = field(default_factory=ScoringWeightsConfig)
    weex: WeexConfig = field(default_factory=WeexConfig)


def load_config(config_path: Optional[str] = None) -> ScannerConfig:
    """Load configuration from .env and optional JSON file."""
    # Load environment variables from .env if present
    load_dotenv()

    config = ScannerConfig()

    # If config file is provided or exists at default path, load JSON
    target_path = config_path or "config.json"
    path_obj = Path(target_path)

    if path_obj.exists():
        try:
            with open(path_obj, "r", encoding="utf-8") as f:
                data = json.load(f)
                _apply_dict_to_config(config, data)
        except Exception as e:
            print(f"[WARN] Failed to parse config JSON at {target_path}: {e}")

    # Override with environment variables if set
    _apply_env_overrides(config)

    # Validate weights sum
    total_weight = (
        config.weights.weight_rs
        + config.weights.weight_volume
        + config.weights.weight_trend
        + config.weights.weight_liquidity
    )
    if abs(total_weight - 1.0) > 0.001:
        print(f"[WARN] Scoring weights sum to {total_weight:.3f}, normalizing to 1.0")
        config.weights.weight_rs /= total_weight
        config.weights.weight_volume /= total_weight
        config.weights.weight_trend /= total_weight
        config.weights.weight_liquidity /= total_weight

    return config


def _apply_dict_to_config(config: ScannerConfig, data: dict[str, Any]) -> None:
    """Apply dictionary fields to config dataclass recursively."""
    if "scan_interval_seconds" in data:
        config.scan_interval_seconds = int(data["scan_interval_seconds"])
    if "cooldown_minutes" in data:
        config.cooldown_minutes = int(data["cooldown_minutes"])
    if "min_alert_score" in data:
        config.min_alert_score = float(data["min_alert_score"])
    if "min_log_score" in data:
        config.min_log_score = float(data["min_log_score"])
    if "database_path" in data:
        config.database_path = str(data["database_path"])
    if "max_pairs" in data:
        config.max_pairs = int(data["max_pairs"])
    if "weex_only_universe" in data:
        config.weex_only_universe = bool(data["weex_only_universe"])
    if "excluded_keywords" in data and isinstance(data["excluded_keywords"], list):
        config.excluded_keywords = data["excluded_keywords"]
    if "request_delay_seconds" in data:
        config.request_delay_seconds = float(data["request_delay_seconds"])

    if "telegram" in data and isinstance(data["telegram"], dict):
        tg = data["telegram"]
        if "bot_token" in tg:
            config.telegram.bot_token = str(tg["bot_token"])
        if "chat_id" in tg:
            config.telegram.chat_id = str(tg["chat_id"])
        if "thread_id" in tg:
            config.telegram.thread_id = int(tg["thread_id"]) if tg["thread_id"] else None
        if "enabled" in tg:
            config.telegram.enabled = bool(tg["enabled"])
        if "send_chart_link" in tg:
            config.telegram.send_chart_link = bool(tg["send_chart_link"])

    if "gates" in data and isinstance(data["gates"], dict):
        g = data["gates"]
        if "min_24h_quote_volume" in g:
            config.gates.min_24h_quote_volume = float(g["min_24h_quote_volume"])
        if "max_spread_bps" in g:
            config.gates.max_spread_bps = float(g["max_spread_bps"])
        if "min_1h_candles" in g:
            config.gates.min_1h_candles = int(g["min_1h_candles"])
        if "max_ema20_1h_extension_pct" in g:
            config.gates.max_ema20_1h_extension_pct = float(g["max_ema20_1h_extension_pct"])
        if "max_daily_bearish_pct" in g:
            config.gates.max_daily_bearish_pct = float(g["max_daily_bearish_pct"])

    if "weights" in data and isinstance(data["weights"], dict):
        w = data["weights"]
        if "weight_rs" in w:
            config.weights.weight_rs = float(w["weight_rs"])
        if "weight_volume" in w:
            config.weights.weight_volume = float(w["weight_volume"])
        if "weight_trend" in w:
            config.weights.weight_trend = float(w["weight_trend"])
        if "weight_liquidity" in w:
            config.weights.weight_liquidity = float(w["weight_liquidity"])

    if "weex" in data and isinstance(data["weex"], dict):
        wx = data["weex"]
        if "enabled" in wx:
            config.weex.enabled = bool(wx["enabled"])
        if "dry_run" in wx:
            config.weex.dry_run = bool(wx["dry_run"])
        if "api_key" in wx:
            config.weex.api_key = str(wx["api_key"])
        if "api_secret" in wx:
            config.weex.api_secret = str(wx["api_secret"])
        if "passphrase" in wx:
            config.weex.passphrase = str(wx["passphrase"])
        if "base_url" in wx:
            config.weex.base_url = str(wx["base_url"])
        if "position_size_pct" in wx:
            config.weex.position_size_pct = float(wx["position_size_pct"])
        if "fixed_order_usdt" in wx:
            config.weex.fixed_order_usdt = float(wx["fixed_order_usdt"]) if wx["fixed_order_usdt"] else None
        if "leverage" in wx:
            config.weex.leverage = int(wx["leverage"])
        if "take_profit_rr" in wx:
            config.weex.take_profit_rr = float(wx["take_profit_rr"])


def _apply_env_overrides(config: ScannerConfig) -> None:
    """Apply environment variables if present."""
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if bot_token:
        config.telegram.bot_token = bot_token.strip().strip("'\"")

    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if chat_id:
        config.telegram.chat_id = chat_id.strip().strip("'\"")

    thread_id = os.getenv("TELEGRAM_THREAD_ID")
    if thread_id:
        try:
            config.telegram.thread_id = int(thread_id)
        except ValueError:
            pass

    tg_enabled = os.getenv("TELEGRAM_ENABLED")
    if tg_enabled is not None:
        config.telegram.enabled = tg_enabled.lower() in ("true", "1", "yes")

    min_volume = os.getenv("MIN_24H_QUOTE_VOLUME")
    if min_volume:
        try:
            config.gates.min_24h_quote_volume = float(min_volume)
        except ValueError:
            pass

    cooldown = os.getenv("COOLDOWN_MINUTES")
    if cooldown:
        try:
            config.cooldown_minutes = int(cooldown)
        except ValueError:
            pass

    db_path = os.getenv("DATABASE_PATH")
    if db_path:
        config.database_path = db_path

    max_pairs_env = os.getenv("MAX_PAIRS")
    if max_pairs_env:
        try:
            config.max_pairs = int(max_pairs_env.strip())
        except ValueError:
            pass

    weex_only_env = os.getenv("WEEX_ONLY_UNIVERSE")
    if weex_only_env is not None:
        config.weex_only_universe = weex_only_env.lower() in ("true", "1", "yes")

    # WEEX environment variables
    weex_enabled = os.getenv("WEEX_ENABLED")
    if weex_enabled is not None:
        config.weex.enabled = weex_enabled.lower() in ("true", "1", "yes")

    weex_dry_run = os.getenv("WEEX_DRY_RUN")
    if weex_dry_run is not None:
        config.weex.dry_run = weex_dry_run.lower() in ("true", "1", "yes")

    weex_key = os.getenv("WEEX_API_KEY")
    if weex_key:
        config.weex.api_key = weex_key.strip()

    weex_secret = os.getenv("WEEX_API_SECRET")
    if weex_secret:
        config.weex.api_secret = weex_secret.strip()

    weex_pass = os.getenv("WEEX_PASSPHRASE")
    if weex_pass:
        config.weex.passphrase = weex_pass.strip()

    weex_base = os.getenv("WEEX_BASE_URL")
    if weex_base:
        config.weex.base_url = weex_base.strip()

    weex_lev = os.getenv("WEEX_LEVERAGE")
    if weex_lev:
        try:
            cleaned_lev = weex_lev.strip().strip("'\"").lower().rstrip("x").strip()
            config.weex.leverage = int(float(cleaned_lev))
        except (ValueError, TypeError) as e:
            print(f"[WARN] Failed to parse WEEX_LEVERAGE='{weex_lev}': {e}. Using default {config.weex.leverage}x")

    weex_pos_pct = os.getenv("WEEX_POSITION_SIZE_PCT")
    if weex_pos_pct:
        try:
            cleaned_pct = weex_pos_pct.strip().strip("'\"").rstrip("%").strip()
            val = float(cleaned_pct)
            if val > 1.0:
                val = val / 100.0
            config.weex.position_size_pct = val
        except (ValueError, TypeError) as e:
            print(f"[WARN] Failed to parse WEEX_POSITION_SIZE_PCT='{weex_pos_pct}': {e}")

    weex_fixed_usdt = os.getenv("WEEX_FIXED_ORDER_USDT")
    if weex_fixed_usdt:
        try:
            cleaned_usdt = weex_fixed_usdt.strip().strip("'\"").lstrip("$").strip()
            config.weex.fixed_order_usdt = float(cleaned_usdt)
        except (ValueError, TypeError) as e:
            print(f"[WARN] Failed to parse WEEX_FIXED_ORDER_USDT='{weex_fixed_usdt}': {e}")
