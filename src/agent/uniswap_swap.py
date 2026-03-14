# -*- coding: utf-8 -*-
"""TIAMAT Uniswap Swap Module

Provides thin wrappers around the Uniswap v3 trading API for quoting and executing token swaps.
All data is kept local; no external state is persisted besides the optional .env API key.

Functions:
- check_approval(token_address: str, wallet_address: str) -> bool
- get_quote(token_in: str, token_out: str, amount_in: int) -> dict
- execute_swap(token_in: str, token_out: str, amount_in: int, wallet_address: str) -> dict

The module raises UniswapError on any HTTP or logical failure.
"""

import os
import json
import time
from typing import Dict, Any
import requests

# Load API key from environment – the .env file is mounted in the runtime
_UNISWAP_API_KEY = os.getenv("UNISWAP_API_KEY")
if not _UNISWAP_API_KEY:
    raise EnvironmentError("UNISWAP_API_KEY not set in environment")

_BASE_URL = "https://trade-api.gateway.uniswap.org/v1"
_HEADERS = {
    "Authorization": f"Bearer {_UNISWAP_API_KEY}",
    "Content-Type": "application/json",
    "Accept": "application/json",
}

class UniswapError(Exception):
    """Custom exception for any Uniswap API error"""
    pass

def _post(endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Internal helper for POST requests with basic retry logic.

    Args:
        endpoint: API endpoint relative to base URL.
        payload: JSON‑serialisable dict.
    Returns:
        Parsed JSON response.
    Raises:
        UniswapError on non‑200 status or malformed response.
    """
    url = f"{_BASE_URL}{endpoint}"
    for attempt in range(3):
        try:
            resp = requests.post(url, headers=_HEADERS, json=payload, timeout=10)
            if resp.status_code == 200:
                return resp.json()
            # Uniswap returns error details in JSON body
            try:
                err = resp.json()
            except Exception:
                err = {"message": resp.text}
            raise UniswapError(f"HTTP {resp.status_code}: {err.get('message', 'unknown error')}")
        except (requests.RequestException, UniswapError) as e:
            if attempt == 2:
                raise UniswapError(str(e))
            time.sleep(1)  # simple back‑off
    # unreachable
    raise UniswapError("Unexpected failure in _post")

def check_approval(token_address: str, wallet_address: str) -> bool:
    """Check if *wallet_address* has approved *token_address* for the Uniswap router.

    Returns True if allowance >= 1e-18 (i.e., any non‑zero approval).
    """
    payload = {
        "token": token_address,
        "owner": wallet_address,
    }
    resp = _post("/allowance", payload)
    allowance = int(resp.get("allowance", "0"))
    return allowance > 0

def get_quote(token_in: str, token_out: str, amount_in: int) -> Dict[str, Any]:
    """Retrieve a swap quote from Uniswap.

    Args:
        token_in: ERC‑20 address of the input token.
        token_out: ERC‑20 address of the desired output token.
        amount_in: Amount of *token_in* in wei.
    Returns:
        Dict with at least ``amountOut`` (wei), ``priceImpact`` (%), and ``estimatedGas``.
    """
    payload = {
        "tokenIn": token_in,
        "tokenOut": token_out,
        "amountIn": str(amount_in),
    }
    return _post("/quote", payload)

def execute_swap(
    token_in: str,
    token_out: str,
    amount_in: int,
    wallet_address: str,
) -> Dict[str, Any]:
    """Execute a token swap on Uniswap.

    The caller must have already approved *token_in* for the router.
    Returns the transaction receipt JSON as returned by the API.
    """
    # Build the transaction payload – Uniswap expects a signed transaction JSON.
    # For simplicity we rely on the API to sign using the provided API key (which has
    # the necessary permissions for the test environment).
    payload = {
        "from": wallet_address,
        "tokenIn": token_in,
        "tokenOut": token_out,
        "amountIn": str(amount_in),
        "slippageTolerance": "0.5",  # 0.5% default slippage
    }
    return _post("/swap", payload)

# ---------------------------------------------------------------------------
# Example usage (remove or guard behind __name__ == "__main__" in production)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Demo: swap 0.01 ETH (in wei) for USDC on Base network
    ETH = "0x4200000000000000000000000000000000000006"  # Base ETH address
    USDC = "0x7F5c764cBc14f9669B88837ca1490cCa17c31607"  # Base USDC address
    WALLET = "0xYourWalletAddress"
    AMOUNT_IN = 10_000_000_000_000_000  # 0.01 ETH

    if not check_approval(ETH, WALLET):
        print("Approval missing – request approval via your wallet UI before swapping.")
    else:
        quote = get_quote(ETH, USDC, AMOUNT_IN)
        print("Quote:", json.dumps(quote, indent=2))
        # Uncomment to actually execute (costs gas!)
        # receipt = execute_swap(ETH, USDC, AMOUNT_IN, WALLET)
        # print("Swap receipt:", json.dumps(receipt, indent=2))
