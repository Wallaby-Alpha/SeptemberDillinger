"""
WEEX V3 Contract API Client for MEXC Accumulation Scanner.
Provides authenticated HMAC-SHA256 order placement, leverage configuration,
account balance inspection, and contract market metadata.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time
from typing import Any, Dict, List, Optional
import requests

from config import WeexConfig

logger = logging.getLogger("WEEX_CLIENT")


class WeexClient:
    def __init__(self, config: WeexConfig):
        self.config = config
        self.api_key = config.api_key.strip()
        self.api_secret = config.api_secret.strip()
        self.passphrase = config.passphrase.strip()
        
        # Defensive cleanup on base_url
        clean_url = config.base_url.strip().strip("'\"")
        if not clean_url.startswith("http"):
            clean_url = f"https://{clean_url}"
        self.base_url = clean_url.rstrip("/")
        self.session = requests.Session()

    def is_configured(self) -> bool:
        """Check if WEEX API credentials are present."""
        return (
            bool(self.api_key)
            and bool(self.api_secret)
            and bool(self.passphrase)
            and self.api_key != "your_weex_api_key_here"
        )

    def generate_signature(self, timestamp: str, method: str, path: str, body_str: str) -> str:
        """
        Generates HMAC-SHA256 signature encoded in Base64:
        message = timestamp + method.upper() + path + body_str
        """
        message = timestamp + method.upper() + path + (body_str or "")
        mac = hmac.new(
            self.api_secret.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        )
        return base64.b64encode(mac.digest()).decode("utf-8")

    def request(
        self,
        method: str,
        path: str,
        body: Optional[Dict[str, Any]] = None,
        is_public: bool = False,
        timeout: int = 12,
    ) -> Dict[str, Any]:
        """
        Executes HTTP request against WEEX V3 Contract endpoints with auth headers.
        """
        url = f"{self.base_url}{path}"
        headers = {
            "Content-Type": "application/json",
            "locale": "en-US",
        }

        body_str = json.dumps(body) if (method.upper() not in ("GET", "DELETE") and body) else ""

        if not is_public:
            if not self.is_configured():
                return {"code": -1, "msg": "WEEX API credentials not configured"}
            timestamp = str(int(time.time() * 1000))
            signature = self.generate_signature(timestamp, method, path, body_str)
            headers.update({
                "ACCESS-KEY": self.api_key,
                "ACCESS-SIGN": signature,
                "ACCESS-TIMESTAMP": timestamp,
                "ACCESS-PASSPHRASE": self.passphrase,
            })

        for attempt in range(3):
            try:
                if method.upper() == "GET":
                    resp = self.session.get(url, headers=headers, timeout=timeout)
                elif method.upper() == "POST":
                    resp = self.session.post(url, headers=headers, data=body_str, timeout=timeout)
                elif method.upper() == "DELETE":
                    resp = self.session.delete(url, headers=headers, timeout=timeout)
                else:
                    raise ValueError(f"Unsupported HTTP method: {method}")

                if resp.status_code == 429:
                    time.sleep(1.5 * (attempt + 1))
                    continue

                try:
                    return resp.json()
                except Exception:
                    return {"code": resp.status_code, "msg": resp.text}

            except Exception as e:
                logger.warning(f"WEEX request attempt {attempt + 1} failed for {method} {path}: {e}")
                time.sleep(1.0)

        return {"code": -1, "msg": "WEEX request failed after 3 attempts"}

    def get_exchange_info(self) -> Dict[str, Dict[str, Any]]:
        """
        Fetches all trading symbol metadata including price/quantity precision and limits.
        Public endpoint: does not require API keys.
        """
        res = self.request("GET", "/capi/v3/market/exchangeInfo", is_public=True)
        raw_symbols = res.get("symbols") or res.get("data", {}).get("symbols") or []
        metadata = {}

        for s in raw_symbols:
            sym = s.get("symbol") or s.get("displaySymbol")
            if sym:
                metadata[sym] = {
                    "symbol": sym,
                    "baseAsset": s.get("baseAsset", "").upper(),
                    "quoteAsset": s.get("quoteAsset", "USDT").upper(),
                    "pricePrecision": int(s.get("pricePrecision", 4)),
                    "quantityPrecision": int(s.get("quantityPrecision", 2)),
                    "contractVal": float(s.get("contractVal", 1.0)),
                    "minOrderSize": float(s.get("minOrderSize", 0.001)),
                    "maxOrderSize": float(s.get("maxOrderSize", 1000000)),
                    "minLeverage": int(s.get("minLeverage", 1)),
                    "maxLeverage": int(s.get("maxLeverage", 100)),
                }
        return metadata

    def get_mark_price(self, symbol: str) -> Optional[float]:
        """Fetches current mark price for a symbol."""
        res = self.request("GET", f"/capi/v3/market/premiumIndex?symbol={symbol}", is_public=True)
        item = res if not isinstance(res, list) else (res[0] if len(res) > 0 else {})
        if "data" in res:
            item = res["data"]
            if isinstance(item, list) and len(item) > 0:
                item = item[0]

        mark_price = item.get("markPrice") or item.get("indexPrice")
        if mark_price:
            try:
                return float(mark_price)
            except (ValueError, TypeError):
                pass
        return None

    def get_available_margin(self) -> float:
        """Fetches available USDT balance in the futures contract account."""
        res = self.request("GET", "/capi/v3/account/balance")
        balances = res if isinstance(res, list) else res.get("data", [])
        if isinstance(balances, dict):
            balances = balances.get("list", []) or [balances]

        for b in balances:
            if not isinstance(b, dict):
                continue
            asset = (b.get("asset") or b.get("marginAsset") or "").upper()
            if asset == "USDT":
                val = (
                    b.get("available")
                    or b.get("availableBalance")
                    or b.get("crossMarginAvailable")
                    or b.get("balance")
                    or b.get("equity")
                    or 0.0
                )
                try:
                    return float(val)
                except (ValueError, TypeError):
                    pass
        return 0.0

    def set_leverage(self, symbol: str, leverage: int = 3) -> bool:
        """Sets isolated leverage for both long and short positions on the contract symbol."""
        payload = {
            "symbol": symbol,
            "isolatedLongLeverage": str(leverage),
            "isolatedShortLeverage": str(leverage),
        }
        res = self.request("POST", "/capi/v3/account/leverage", payload)
        if not isinstance(res, dict):
            return False
        code = str(res.get("code", ""))
        return (
            code in ("0", "00000", "200")
            or res.get("symbol") == symbol
            or "crossLeverage" in res
            or "isolatedLongLeverage" in res
            or res.get("success", False)
        )

    def place_order_with_tpsl(
        self,
        symbol: str,
        side: str,              # "BUY" or "SELL"
        position_side: str,     # "LONG" or "SHORT"
        quantity: float,
        tp_price: Optional[float] = None,
        sl_price: Optional[float] = None,
        client_order_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Places a market contract order on WEEX V3 (/capi/v3/order) with attached Take Profit & Stop Loss.
        """
        client_id = client_order_id or f"mexc-{int(time.time() * 1000)}"

        # Clean quantity representation (avoid decimal for whole contract counts)
        try:
            qty_val = float(quantity)
            qty_str = str(int(qty_val)) if qty_val.is_integer() else str(qty_val)
        except (ValueError, TypeError):
            qty_str = str(quantity)

        payload: Dict[str, Any] = {
            "symbol": symbol,
            "side": side.upper(),
            "type": "MARKET",
            "positionSide": position_side.upper(),
            "quantity": qty_str,
            "newClientOrderId": client_id,
        }

        # Defensively attach Take Profit plan if provided
        if tp_price is not None:
            try:
                if float(tp_price) > 0:
                    payload["tpTriggerPrice"] = str(tp_price)
                    payload["tpWorkingType"] = "MARK_PRICE"
            except (ValueError, TypeError):
                pass

        # Defensively attach Stop Loss plan if provided
        if sl_price is not None:
            try:
                if float(sl_price) > 0:
                    payload["slTriggerPrice"] = str(sl_price)
                    payload["slWorkingType"] = "MARK_PRICE"
            except (ValueError, TypeError):
                pass

        res = self.request("POST", "/capi/v3/order", payload)
        order_data = res.get("data", {}) if isinstance(res, dict) else {}
        order_id = None
        if isinstance(order_data, dict):
            order_id = order_data.get("orderId")
        if not order_id and isinstance(res, dict):
            order_id = res.get("orderId")

        code = str(res.get("code", "")) if isinstance(res, dict) else ""
        http_status = res.get("status") if isinstance(res, dict) else None
        success = (
            http_status != 404
            and (code in ("0", "00000", "200") or bool(order_id) or (isinstance(res, dict) and res.get("success", False)))
        )
        return {
            "success": success,
            "orderId": str(order_id or ""),
            "raw": res,
        }
