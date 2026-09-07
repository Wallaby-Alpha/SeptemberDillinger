#!/usr/bin/env python3
"""
Diagnostic utility to verify WEEX V3 Contract API credentials,
network connectivity, IP whitelisting, and account balances.
"""

import os
import sys
import json
import time
import requests
from dotenv import load_dotenv

# Load .env from current directory or parent
load_dotenv()

from config import load_config
from weex_client import WeexClient

def main():
    print("=" * 60)
    print("[DIAGNOSTIC] WEEX V3 CONTRACT API AUTHENTICATION CHECK")
    print("=" * 60)

    # 1. Check Public IP (for IP whitelist verification)
    try:
        my_ip = requests.get("https://api.ipify.org?format=json", timeout=5).json().get("ip")
        print(f"[IP] Server Outbound IPv4: {my_ip}")
        print("     (Ensure this IP is added to your WEEX API Key Whitelist if restricted)")
    except Exception as e:
        print(f"[WARN] Could not resolve outbound IP: {e}")

    print("-" * 60)

    # 2. Check Loaded Credentials
    cfg = load_config()
    weex_cfg = cfg.weex

    raw_key = os.getenv("WEEX_API_KEY") or os.getenv("WEEX_KEY") or ""
    raw_secret = os.getenv("WEEX_API_SECRET") or os.getenv("WEEX_SECRET") or ""
    raw_pass = os.getenv("WEEX_PASSPHRASE") or os.getenv("WEEX_API_PASSPHRASE") or ""

    clean_key = weex_cfg.api_key
    clean_secret = weex_cfg.api_secret
    clean_pass = weex_cfg.passphrase

    def mask(s):
        if not s:
            return "<EMPTY / NOT SET>"
        if len(s) <= 8:
            return s[:2] + "****" + s[-2:]
        return s[:4] + "****" + s[-4:] + f" (len: {len(s)})"

    print("[CREDS] Loaded Credentials:")
    print(f" - WEEX_ENABLED:       {weex_cfg.enabled}")
    print(f" - WEEX_DRY_RUN:       {weex_cfg.dry_run}")
    print(f" - WEEX_BASE_URL:      {weex_cfg.base_url}")
    print(f" - WEEX_API_KEY:       {mask(clean_key)}")
    print(f" - WEEX_API_SECRET:    {mask(clean_secret)}")
    print(f" - WEEX_PASSPHRASE:    {mask(clean_pass)}")

    if not clean_key or not clean_secret or not clean_pass:
        print("\n[ERROR] One or more WEEX credentials are missing in your .env file!")
        print("   Make sure WEEX_API_KEY, WEEX_API_SECRET, and WEEX_PASSPHRASE are set.")
        sys.exit(1)

    print("-" * 60)
    print("[SENDING] Authenticated request to WEEX Contract API (/capi/v3/account/balance)...")

    client = WeexClient(weex_cfg)

    # Test 1: Standard Live Request
    res = client.request("GET", "/capi/v3/account/balance")
    print(f"[HTTP] Response Code: {res.get('code')}")
    print(f"[HTTP] Response Msg:  {res.get('msg', 'N/A')}")

    if res.get("code") in (0, "0", "00000", 200) or "data" in res:
        print("\n[SUCCESS] WEEX Contract API accepted your keys!")
        balances = res.get("data") or res.get("list") or res
        print(f"[DATA] Account Data: {json.dumps(balances, indent=2)[:300]}...")
        return

    # Test 2: If -1044, check with Demo headers
    if res.get("code") == -1044:
        print("\n[WARN] Code -1044: Invalid ACCESS_KEY.")
        print("   Checking if this is a WEEX Demo account key...")
        
        # Test with demo simulation header
        orig_req = client.request
        headers_demo = {
            "X-SIMULATED-TRADING": "1",
            "paptrading": "1",
            "X-WEEX-DEMO": "true",
        }
        # Direct request test
        timestamp = str(int(time.time() * 1000))
        sig = client.generate_signature(timestamp, "GET", "/capi/v3/account/balance", "")
        h = {
            "Content-Type": "application/json",
            "locale": "en-US",
            "ACCESS-KEY": clean_key,
            "ACCESS-SIGN": sig,
            "ACCESS-TIMESTAMP": timestamp,
            "ACCESS-PASSPHRASE": clean_pass,
            **headers_demo,
        }
        demo_res = requests.get(f"{weex_cfg.base_url}/capi/v3/account/balance", headers=h, timeout=10).json()
        print(f"   Demo Header Test Result: {demo_res}")

        print("\n" + "=" * 60)
        print("📌 ROOT CAUSE ANALYSIS FOR -1044 (Invalid ACCESS_KEY):")
        print(" 1. CONTRACT VS SPOT KEY:")
        print("    WEEX has separate API keys for Spot vs Futures (Contract).")
        print("    The bot uses Contract API (/capi/v3/). Ensure your API key was created")
        print("    under 'Futures/Contract API' on WEEX, NOT 'Spot API'.")
        print(" 2. IP WHITELIST RESTRICTION:")
        print(f"    If you enabled IP restrictions on WEEX, your droplet IP ({my_ip})")
        print("    must be whitelisted in the WEEX API management console.")
        print(" 3. DEMO VS REAL ENVIRONMENT:")
        print("    If your API key was generated inside WEEX Demo Trading, set:")
        print("    WEEX_DEMO=true in your .env file.")
        print(" 4. TYPO OR QUOTES:")
        print("    Check your .env on the droplet: nano .env")
        print("    Remove any quotes around the keys, e.g. WEEX_API_KEY=my_key")
        print("=" * 60)

if __name__ == "__main__":
    main()
