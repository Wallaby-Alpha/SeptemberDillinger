"""
Scoring module for MEXC Quiet Accumulation Scanner.
Implements Hard Gate validation and multi-factor Stage 1 scoring:
1. Relative Strength vs BTC (6h)
2. Volume Acceleration (gradual ramp 1.2x - 3.0x, penalizes extreme spikes)
3. Trend Structure (Price > EMA20, EMA20 > EMA50, EMA20 upward slope)
4. Liquidity & Spread baseline
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple
import numpy as np
import pandas as pd

from config import HardGatesConfig, ScoringWeightsConfig


@dataclass
class GateCheckResult:
    passed: bool
    reason: str
    quote_volume_24h: float
    spread_bps: float
    candle_count_1h: int
    ema20_1h_ext_pct: float
    daily_ema20_diff_pct: float


@dataclass
class ScoringResult:
    symbol: str
    price: float
    final_score: float
    stage: str
    is_stage1: bool
    
    # Component Scores (0.0 to 1.0)
    rs_score: float
    vol_score: float
    trend_score: float
    liq_score: float
    
    # Raw Metrics
    alt_return_6h_pct: float
    btc_return_6h_pct: float
    rs_diff_pct: float
    vol_ratio: float
    ema20_1h: float
    ema50_1h: float
    daily_ema20: float
    ema20_slope_positive: bool
    spread_bps: float
    quote_volume_24h: float
    
    # Trade Levels
    suggested_entry_low: float
    suggested_entry_high: float
    suggested_stop: float
    risk_to_stop_pct: float


def compute_ema(series: pd.Series, period: int) -> pd.Series:
    """Calculate Exponential Moving Average."""
    return series.ewm(span=period, adjust=False).mean()


def evaluate_hard_gates(
    df_1h: pd.DataFrame,
    df_1d: Optional[pd.DataFrame],
    quote_volume_24h: float,
    spread_bps: float,
    gates: HardGatesConfig,
) -> GateCheckResult:
    """
    Evaluate all mandatory Hard Gates before scoring:
    1. Min 24h quote volume >= $250,000
    2. Order-book spread <= 80 bps
    3. At least 100 historical 1h candles
    4. Price not extended > 12% above 1h EMA20
    5. Daily trend not strongly bearish (price not > 5% below daily EMA20)
    """
    candle_count_1h = len(df_1h)

    # 1. 1h Candle History Gate
    if candle_count_1h < gates.min_1h_candles:
        return GateCheckResult(
            passed=False,
            reason=f"Insufficient 1h candles: {candle_count_1h} < {gates.min_1h_candles}",
            quote_volume_24h=quote_volume_24h,
            spread_bps=spread_bps,
            candle_count_1h=candle_count_1h,
            ema20_1h_ext_pct=0.0,
            daily_ema20_diff_pct=0.0,
        )

    # 2. Volume Gate
    if quote_volume_24h < gates.min_24h_quote_volume:
        return GateCheckResult(
            passed=False,
            reason=f"Low 24h quote volume: ${quote_volume_24h:,.0f} < ${gates.min_24h_quote_volume:,.0f}",
            quote_volume_24h=quote_volume_24h,
            spread_bps=spread_bps,
            candle_count_1h=candle_count_1h,
            ema20_1h_ext_pct=0.0,
            daily_ema20_diff_pct=0.0,
        )

    # 3. Spread Gate
    if spread_bps > gates.max_spread_bps:
        return GateCheckResult(
            passed=False,
            reason=f"Wide spread: {spread_bps:.1f} bps > {gates.max_spread_bps:.1f} bps",
            quote_volume_24h=quote_volume_24h,
            spread_bps=spread_bps,
            candle_count_1h=candle_count_1h,
            ema20_1h_ext_pct=0.0,
            daily_ema20_diff_pct=0.0,
        )

    # 4. 1h EMA20 Overextension Gate
    ema20_1h_series = compute_ema(df_1h["close"], 20)
    current_price = float(df_1h["close"].iloc[-1])
    current_ema20_1h = float(ema20_1h_series.iloc[-1])

    if current_ema20_1h <= 0:
        return GateCheckResult(
            passed=False,
            reason="Invalid 1h EMA20 value <= 0",
            quote_volume_24h=quote_volume_24h,
            spread_bps=spread_bps,
            candle_count_1h=candle_count_1h,
            ema20_1h_ext_pct=0.0,
            daily_ema20_diff_pct=0.0,
        )

    ema20_1h_ext_pct = (current_price - current_ema20_1h) / current_ema20_1h
    if ema20_1h_ext_pct > gates.max_ema20_1h_extension_pct:
        return GateCheckResult(
            passed=False,
            reason=f"Overextended: {ema20_1h_ext_pct*100:.2f}% > {gates.max_ema20_1h_extension_pct*100:.1f}% above 1h EMA20",
            quote_volume_24h=quote_volume_24h,
            spread_bps=spread_bps,
            candle_count_1h=candle_count_1h,
            ema20_1h_ext_pct=ema20_1h_ext_pct,
            daily_ema20_diff_pct=0.0,
        )

    # 5. Daily Trend Gate (if daily candles available, check against EMA20)
    daily_ema20_diff_pct = 0.0
    if df_1d is not None and len(df_1d) >= 20:
        daily_ema20_series = compute_ema(df_1d["close"], 20)
        daily_close = float(df_1d["close"].iloc[-1])
        daily_ema20 = float(daily_ema20_series.iloc[-1])
        if daily_ema20 > 0:
            daily_ema20_diff_pct = (daily_close - daily_ema20) / daily_ema20
            if daily_ema20_diff_pct < gates.max_daily_bearish_pct:
                return GateCheckResult(
                    passed=False,
                    reason=f"Strongly bearish daily trend: {daily_ema20_diff_pct*100:.2f}% < {gates.max_daily_bearish_pct*100:.1f}% vs Daily EMA20",
                    quote_volume_24h=quote_volume_24h,
                    spread_bps=spread_bps,
                    candle_count_1h=candle_count_1h,
                    ema20_1h_ext_pct=ema20_1h_ext_pct,
                    daily_ema20_diff_pct=daily_ema20_diff_pct,
                )

    return GateCheckResult(
        passed=True,
        reason="Passed all gates",
        quote_volume_24h=quote_volume_24h,
        spread_bps=spread_bps,
        candle_count_1h=candle_count_1h,
        ema20_1h_ext_pct=ema20_1h_ext_pct,
        daily_ema20_diff_pct=daily_ema20_diff_pct,
    )


def compute_relative_strength_score(
    df_alt_1h: pd.DataFrame,
    df_btc_1h: pd.DataFrame,
) -> Tuple[float, float, float, float]:
    """
    Compute 6h Relative Strength vs BTC.
    Returns: (rs_score, alt_ret_6h_pct, btc_ret_6h_pct, rs_diff_pct)
    """
    if len(df_alt_1h) < 7 or len(df_btc_1h) < 7:
        return 0.5, 0.0, 0.0, 0.0

    alt_close_now = float(df_alt_1h["close"].iloc[-1])
    alt_close_6h_ago = float(df_alt_1h["close"].iloc[-7])
    alt_ret_6h = (alt_close_now - alt_close_6h_ago) / max(alt_close_6h_ago, 1e-9)

    btc_close_now = float(df_btc_1h["close"].iloc[-1])
    btc_close_6h_ago = float(df_btc_1h["close"].iloc[-7])
    btc_ret_6h = (btc_close_now - btc_close_6h_ago) / max(btc_close_6h_ago, 1e-9)

    rs_diff = alt_ret_6h - btc_ret_6h  # e.g. +0.03 is +3% outperformance

    # Map rs_diff to [0.0, 1.0]
    # Neutral (matching BTC, 0% diff) -> 0.50
    # +6% outperformance over 6h -> 1.00
    # -6% underperformance -> 0.00
    rs_score = float(np.clip(0.50 + (rs_diff / 0.12), 0.0, 1.0))

    return rs_score, alt_ret_6h * 100.0, btc_ret_6h * 100.0, rs_diff * 100.0


def compute_volume_acceleration_score(df_1h: pd.DataFrame) -> Tuple[float, float]:
    """
    Compute Volume Acceleration score.
    Prefers gradual ramp (1.2x - 3.0x recent 3h avg vs prior 15h base avg).
    Penalizes extreme spikes (>5.0x) to avoid chasing blow-offs.
    Returns: (vol_score, vol_ratio)
    """
    if len(df_1h) < 18:
        return 0.5, 1.0

    recent_vol = float(df_1h["volume"].iloc[-3:].mean())
    prior_base_vol = float(df_1h["volume"].iloc[-18:-3].mean())

    if prior_base_vol <= 0:
        vol_ratio = 1.0
    else:
        vol_ratio = recent_vol / prior_base_vol

    # Scoring curve
    if vol_ratio < 0.8:
        # Anemic volume
        vol_score = 0.20
    elif 0.8 <= vol_ratio < 1.2:
        # Normal baseline
        vol_score = 0.50 + ((vol_ratio - 0.8) / 0.4) * 0.25  # 0.50 -> 0.75
    elif 1.2 <= vol_ratio <= 3.0:
        # Sweet spot for Quiet Accumulation
        vol_score = 0.75 + ((vol_ratio - 1.2) / 1.8) * 0.25  # 0.75 -> 1.00
    elif 3.0 < vol_ratio <= 5.0:
        # Getting loud / hot
        vol_score = 1.00 - ((vol_ratio - 3.0) / 2.0) * 0.35  # 1.00 -> 0.65
    else:
        # Extreme blow-off spike penalty (>5.0x)
        vol_score = 0.30

    return float(np.clip(vol_score, 0.0, 1.0)), float(vol_ratio)


def compute_trend_structure_score(
    df_1h: pd.DataFrame,
) -> Tuple[float, float, float, bool]:
    """
    Compute Trend Structure score:
    - Price > EMA20 (weight 0.35)
    - EMA20 > EMA50 (weight 0.35)
    - EMA20 sloping upward: EMA20[-1] > EMA20[-3] (weight 0.30)
    Returns: (trend_score, ema20_1h, ema50_1h, ema20_slope_positive)
    """
    if len(df_1h) < 50:
        return 0.0, 0.0, 0.0, False

    ema20_series = compute_ema(df_1h["close"], 20)
    ema50_series = compute_ema(df_1h["close"], 50)

    price = float(df_1h["close"].iloc[-1])
    ema20_now = float(ema20_series.iloc[-1])
    ema20_prev3 = float(ema20_series.iloc[-3])
    ema50_now = float(ema50_series.iloc[-1])

    score = 0.0

    # 1. Price vs EMA20
    if price >= ema20_now:
        score += 0.35
    elif price >= ema20_now * 0.99:
        score += 0.20  # Touching / kissing EMA20

    # 2. EMA20 vs EMA50
    if ema20_now >= ema50_now:
        score += 0.35
    elif ema20_now >= ema50_now * 0.995:
        score += 0.15  # Near golden cross

    # 3. EMA20 Slope
    slope_positive = ema20_now > ema20_prev3
    if slope_positive:
        score += 0.30

    return float(np.clip(score, 0.0, 1.0)), ema20_now, ema50_now, slope_positive


def compute_liquidity_score(spread_bps: float, max_spread_bps: float) -> float:
    """
    Compute Liquidity & Spread baseline score:
    Tighter spread (< 20 bps) gets high score (1.0).
    Spread near max_spread_bps gets low score (0.0).
    """
    if max_spread_bps <= 0:
        return 1.0
    score = 1.0 - (spread_bps / max_spread_bps)
    return float(np.clip(score, 0.0, 1.0))


def calculate_quiet_accumulation_score(
    symbol: str,
    df_alt_1h: pd.DataFrame,
    df_alt_1d: Optional[pd.DataFrame],
    df_btc_1h: pd.DataFrame,
    quote_volume_24h: float,
    spread_bps: float,
    weights: ScoringWeightsConfig,
    gates: HardGatesConfig,
) -> ScoringResult:
    """
    Master scoring function for Quiet Accumulation (Stage 1).
    Evaluates RS vs BTC, Volume ramp, Trend alignment, and Liquidity.
    """
    current_price = float(df_alt_1h["close"].iloc[-1])

    # 1. Relative Strength vs BTC (6h)
    rs_score, alt_ret_6h, btc_ret_6h, rs_diff = compute_relative_strength_score(
        df_alt_1h, df_btc_1h
    )

    # 2. Volume Acceleration
    vol_score, vol_ratio = compute_volume_acceleration_score(df_alt_1h)

    # 3. Trend Structure
    trend_score, ema20_1h, ema50_1h, slope_pos = compute_trend_structure_score(df_alt_1h)

    # 4. Liquidity / Spread baseline
    liq_score = compute_liquidity_score(spread_bps, gates.max_spread_bps)

    # 5. Daily EMA20 for context
    daily_ema20 = 0.0
    if df_alt_1d is not None and len(df_alt_1d) >= 20:
        daily_ema20 = float(compute_ema(df_alt_1d["close"], 20).iloc[-1])

    # Final Weighted Sum
    final_score = (
        rs_score * weights.weight_rs
        + vol_score * weights.weight_volume
        + trend_score * weights.weight_trend
        + liq_score * weights.weight_liquidity
    )
    final_score = float(np.clip(final_score, 0.0, 1.0))

    # Stage Classification
    # Stage 1: Strictly orderly quiet accumulation, price not blown out, healthy volume ramp, positive trend/RS
    price_to_ema20_pct = (current_price - ema20_1h) / max(ema20_1h, 1e-9)
    is_not_extended = price_to_ema20_pct <= gates.max_ema20_1h_extension_pct
    is_sound_trend = trend_score >= 0.60
    is_healthy_volume = 1.10 <= vol_ratio <= 4.0  # Backtested quality filter: min 1.10x ramp
    is_positive_rs = rs_diff >= 1.50               # Backtested quality filter: min +1.50% RS diff

    if is_not_extended and is_sound_trend and is_healthy_volume and is_positive_rs:
        stage = "Stage 1 (Quiet Accumulation)"
        is_stage1 = True
    elif price_to_ema20_pct > gates.max_ema20_1h_extension_pct or vol_ratio > 4.5:
        stage = "Stage 2 (Markup / Extended)"
        is_stage1 = False
    elif trend_score < 0.35:
        stage = "Stage 4 (Downtrend / Distribution)"
        is_stage1 = False
    else:
        stage = "Stage 1 (Consolidation / Building)"
        is_stage1 = False  # DO NOT ALERT on Building/Consolidation (negative EV in backtest)

    # Trade Levels Suggestion
    # Entry zone: from current price down to 1h EMA20
    suggested_entry_high = current_price
    suggested_entry_low = min(current_price, ema20_1h if ema20_1h > 0 else current_price * 0.98)

    # Calibrated -3.50% Hard Stop Loss
    suggested_stop = current_price * (1.0 - 0.035)
    risk_to_stop_pct = 3.50

    return ScoringResult(
        symbol=symbol,
        price=current_price,
        final_score=round(final_score, 4),
        stage=stage,
        is_stage1=is_stage1,
        rs_score=round(rs_score, 4),
        vol_score=round(vol_score, 4),
        trend_score=round(trend_score, 4),
        liq_score=round(liq_score, 4),
        alt_return_6h_pct=round(alt_ret_6h, 2),
        btc_return_6h_pct=round(btc_ret_6h, 2),
        rs_diff_pct=round(rs_diff, 2),
        vol_ratio=round(vol_ratio, 2),
        ema20_1h=ema20_1h,
        ema50_1h=ema50_1h,
        daily_ema20=daily_ema20,
        ema20_slope_positive=slope_pos,
        spread_bps=round(spread_bps, 2),
        quote_volume_24h=round(quote_volume_24h, 2),
        suggested_entry_low=suggested_entry_low,
        suggested_entry_high=suggested_entry_high,
        suggested_stop=suggested_stop,
        risk_to_stop_pct=round(risk_to_stop_pct, 2),
    )
