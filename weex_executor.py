"""
WEEX Trade Executor for MEXC Quiet Accumulation Scanner.
Automatically translates high-scoring Stage 1 Accumulation alerts into WEEX contract
positions with position sizing, isolated leverage, and native TP/SL order protection.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import math
from typing import Any, Dict, Optional

from config import WeexConfig
from scoring import ScoringResult
from weex_client import WeexClient
from weex_resolver import ResolvedWeexSymbol, WeexSymbolResolver

logger = logging.getLogger("WEEX_EXECUTOR")


@dataclass
class WeexExecutionOutcome:
    status: str              # "EXECUTED", "SIMULATED", "UNLISTED", "DISABLED", "FAILED"
    weex_symbol: Optional[str]
    side: str
    quantity: float
    entry_price: float
    stop_loss: float
    take_profit: float
    leverage: int
    notional_usd: float = 0.0
    order_id: Optional[str] = None
    message: str = ""


class WeexTradeExecutor:
    def __init__(self, config: WeexConfig, client: WeexClient, resolver: WeexSymbolResolver):
        self.config = config
        self.client = client
        self.resolver = resolver

    def execute_alert_signal(self, result: ScoringResult) -> WeexExecutionOutcome:
        """
        Processes a Stage 1 Accumulation alert and converts it into a WEEX trade.
        Safely handles unlisted tokens, multiplier adjustments, and dry-run testing.
        """
        if not self.config.enabled:
            return WeexExecutionOutcome(
                status="DISABLED",
                weex_symbol=None,
                side="NONE",
                quantity=0.0,
                entry_price=result.price,
                stop_loss=0.0,
                take_profit=0.0,
                leverage=self.config.leverage,
                message="WEEX execution is disabled in config.",
            )

        # 1. Resolve MEXC symbol to WEEX Contract symbol
        try:
            resolved = self.resolver.resolve(result.symbol)
        except Exception as e:
            logger.error(f"[WEEX_EXECUTOR] Error during symbol resolution for {result.symbol}: {e}")
            resolved = None

        if not resolved:
            msg = f"Token '{result.symbol}' is not listed on WEEX Contracts. Skipping trade execution."
            logger.info(f"[WEEX_EXECUTOR] {msg}")
            return WeexExecutionOutcome(
                status="UNLISTED",
                weex_symbol=None,
                side="NONE",
                quantity=0.0,
                entry_price=result.price,
                stop_loss=0.0,
                take_profit=0.0,
                leverage=self.config.leverage,
                message=msg,
            )

        # 2. Determine contract entry price and mark price
        weex_mark = self.client.get_mark_price(resolved.weex_symbol)
        if weex_mark is not None:
            try:
                if float(weex_mark) > 0:
                    entry_price = float(weex_mark)
                else:
                    entry_price = float(result.price) * float(resolved.multiplier)
            except (ValueError, TypeError):
                entry_price = float(result.price) * float(resolved.multiplier)
        else:
            entry_price = float(result.price) * float(resolved.multiplier)

        # 3. Position Sizing
        try:
            available_balance = self.client.get_available_margin()
        except Exception:
            available_balance = 0.0

        if available_balance <= 0:
            available_balance = 1000.0  # Safe simulation baseline

        leverage = min(int(self.config.leverage), int(resolved.max_leverage))

        fixed_usdt = None
        if self.config.fixed_order_usdt is not None:
            try:
                fixed_usdt = float(self.config.fixed_order_usdt)
            except (ValueError, TypeError):
                fixed_usdt = None

        if fixed_usdt is not None and fixed_usdt > 0:
            allocated = fixed_usdt
            notional = allocated * leverage
            sizing_mode = f"Fixed ${allocated:.2f} USDT"
        else:
            pos_pct = float(self.config.position_size_pct)
            allocated = available_balance * pos_pct
            notional = allocated * leverage
            sizing_mode = f"{pos_pct * 100:.1f}% of ${available_balance:.2f} balance"

        raw_qty = notional / entry_price
        qty_prec = int(resolved.quantity_precision)
        price_prec = int(resolved.price_precision)
        qty_factor = 10 ** qty_prec
        quantity = math.floor(raw_qty * qty_factor) / qty_factor
        clamped_to_min = False
        min_order = float(resolved.min_order_size)
        if quantity < min_order:
            quantity = min_order
            clamped_to_min = True
        if qty_prec == 0 or quantity.is_integer():
            quantity = int(quantity)

        notional_usd = float(quantity) * entry_price
        clamp_note = f" [CLAMPED to minOrderSize={resolved.min_order_size}]" if clamped_to_min else ""
        logger.info(
            f"[WEEX SIZING] {resolved.weex_symbol} | Mode: {sizing_mode} | "
            f"Notional: ${notional:.2f} (Allocated: ${allocated:.2f} x {leverage}x Lev) | "
            f"MarkPrice: ${entry_price:.4f} | RawQty: {raw_qty:.4f} -> FinalQty: {quantity}{clamp_note} (~${notional_usd:.2f} USD)"
        )

        # 4. Stop Loss & Take Profit Price Calculation
        res_price = float(result.price) if result.price else entry_price
        scale_ratio = entry_price / res_price if res_price > 0 else 1.0
        sl_price = round(float(result.suggested_stop) * scale_ratio, price_prec)

        # Ensure SL is below entry for Long
        if sl_price >= entry_price:
            sl_price = round(entry_price * 0.96, price_prec)

        # Take Profit target: 2:1 R:R target
        risk_per_unit = max(entry_price - sl_price, entry_price * 0.02)
        tp_price = round(entry_price + (risk_per_unit * float(self.config.take_profit_rr)), price_prec)
        if price_prec == 0:
            sl_price = int(sl_price)
            tp_price = int(tp_price)

        # 5. Dry-Run Execution Mode
        if self.config.dry_run:
            log_msg = (
                f"[WEEX DRY-RUN] Simulated LONG on {resolved.weex_symbol} "
                f"| Qty: {quantity} (~${notional_usd:.2f} USD) | Leverage: {leverage}x | Entry: ${entry_price:.4f} "
                f"| SL: ${sl_price:.4f} | TP: ${tp_price:.4f}"
            )
            logger.info(log_msg)
            return WeexExecutionOutcome(
                status="SIMULATED",
                weex_symbol=resolved.weex_symbol,
                side="LONG",
                quantity=quantity,
                entry_price=entry_price,
                stop_loss=sl_price,
                take_profit=tp_price,
                leverage=leverage,
                notional_usd=notional_usd,
                message=log_msg,
            )

        # 6. Live Order Execution
        try:
            # Set leverage
            self.client.set_leverage(resolved.weex_symbol, leverage)

            # Submit order with native TP/SL
            order_res = self.client.place_order_with_tpsl(
                symbol=resolved.weex_symbol,
                side="BUY",
                position_side="LONG",
                quantity=quantity,
                tp_price=tp_price,
                sl_price=sl_price,
            )

            if order_res.get("success"):
                order_id = str(order_res.get("orderId", ""))
                success_msg = (
                    f"LIVE WEEX ORDER PLACED on {resolved.weex_symbol}: "
                    f"LONG {quantity} units (~${notional_usd:.2f} USD) @ ${entry_price:.4f} (Order ID: {order_id})"
                )
                logger.info(f"[WEEX_EXECUTOR] {success_msg}")
                return WeexExecutionOutcome(
                    status="EXECUTED",
                    weex_symbol=resolved.weex_symbol,
                    side="LONG",
                    quantity=quantity,
                    entry_price=entry_price,
                    stop_loss=sl_price,
                    take_profit=tp_price,
                    leverage=leverage,
                    notional_usd=notional_usd,
                    order_id=order_id,
                    message=success_msg,
                )
            else:
                err_msg = f"WEEX order placement rejected for {resolved.weex_symbol}: {order_res.get('raw')}"
                logger.error(f"[WEEX_EXECUTOR] {err_msg}")
                return WeexExecutionOutcome(
                    status="FAILED",
                    weex_symbol=resolved.weex_symbol,
                    side="LONG",
                    quantity=quantity,
                    entry_price=entry_price,
                    stop_loss=sl_price,
                    take_profit=tp_price,
                    leverage=leverage,
                    message=err_msg,
                )

        except Exception as e:
            err_msg = f"Fatal execution exception on {resolved.weex_symbol}: {e}"
            logger.error(f"[WEEX_EXECUTOR] {err_msg}", exc_info=True)
            return WeexExecutionOutcome(
                status="FAILED",
                weex_symbol=resolved.weex_symbol,
                side="LONG",
                quantity=quantity,
                entry_price=entry_price,
                stop_loss=sl_price,
                take_profit=tp_price,
                leverage=leverage,
                message=err_msg,
            )
