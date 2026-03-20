#!/usr/bin/env python3
"""
Execute skim() on Uniswap V2 pairs with excess tokens.
Pre-flight checks: verifies excess exists, token isn't a honeypot,
and skim() gas estimate is sane before sending real tx.

Usage: python3 skim_executor.py <pair_address>
"""
import sys
import json
import os
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware
from eth_account import Account

PRIVATE_KEY = os.environ.get("TIAMAT_WALLET_KEY")
if not PRIVATE_KEY:
    print("Set TIAMAT_WALLET_KEY in /root/.env")
    sys.exit(1)

account = Account.from_key(PRIVATE_KEY)
w3 = Web3(Web3.HTTPProvider("https://base.drpc.org"))
try:
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
except Exception:
    pass

WETH = "0x4200000000000000000000000000000000000006"
MAX_SKIM_GAS = 100_000
HONEYPOT_GAS_THRESHOLD = 50_000

PAIR_ABI = json.loads("""[
{"constant":false,"inputs":[{"name":"to","type":"address"}],"name":"skim","outputs":[],"type":"function"},
{"constant":true,"inputs":[],"name":"getReserves","outputs":[{"name":"","type":"uint112"},{"name":"","type":"uint112"},{"name":"","type":"uint32"}],"type":"function"},
{"constant":true,"inputs":[],"name":"token0","outputs":[{"name":"","type":"address"}],"type":"function"},
{"constant":true,"inputs":[],"name":"token1","outputs":[{"name":"","type":"address"}],"type":"function"}
]""")

ERC20_ABI = json.loads("""[
{"constant":true,"inputs":[{"name":"","type":"address"}],"name":"balanceOf","outputs":[{"name":"","type":"uint256"}],"type":"function"},
{"constant":true,"inputs":[],"name":"symbol","outputs":[{"name":"","type":"string"}],"type":"function"}
]""")


def check_honeypot(token_addr, pair_addr):
    """Returns True if token transfer costs >50K gas (honeypot/gas burner)."""
    try:
        calldata = ("0xa9059cbb"
                     + "0" * 24 + account.address[2:].lower().zfill(40)
                     + "0" * 63 + "1")
        gas = w3.eth.estimate_gas({
            "from": Web3.to_checksum_address(pair_addr),
            "to": Web3.to_checksum_address(token_addr),
            "data": calldata,
        })
        if gas > HONEYPOT_GAS_THRESHOLD:
            print(f"  HONEYPOT: {token_addr} transfer costs {gas} gas (>{HONEYPOT_GAS_THRESHOLD})")
            return True
        return False
    except Exception as e:
        print(f"  HONEYPOT: {token_addr} transfer reverts ({str(e)[:60]})")
        return True


def preflight(pair_address):
    """Run all checks before sending skim(). Returns True if safe to execute."""
    pair_addr = Web3.to_checksum_address(pair_address)
    pair = w3.eth.contract(address=pair_addr, abi=PAIR_ABI)

    # 1. Get reserves and token balances
    reserves = pair.functions.getReserves().call()
    token0 = pair.functions.token0().call()
    token1 = pair.functions.token1().call()

    t0 = w3.eth.contract(address=Web3.to_checksum_address(token0), abi=ERC20_ABI)
    t1 = w3.eth.contract(address=Web3.to_checksum_address(token1), abi=ERC20_ABI)

    bal0 = t0.functions.balanceOf(pair_addr).call()
    bal1 = t1.functions.balanceOf(pair_addr).call()

    excess0 = bal0 - reserves[0]
    excess1 = bal1 - reserves[1]

    sym0 = sym1 = "?"
    try: sym0 = t0.functions.symbol().call()
    except: pass
    try: sym1 = t1.functions.symbol().call()
    except: pass

    print(f"  Token0 ({sym0}): excess={excess0}")
    print(f"  Token1 ({sym1}): excess={excess1}")

    # 2. Check there's actually something to skim
    if excess0 <= 0 and excess1 <= 0:
        print("  ABORT: No excess tokens to skim")
        return False

    # 3. Honeypot check on tokens with excess
    if excess0 > 0 and check_honeypot(token0, pair_addr):
        return False
    if excess1 > 0 and check_honeypot(token1, pair_addr):
        return False

    # 4. Estimate gas for skim() itself
    try:
        skim_gas = w3.eth.estimate_gas({
            "from": account.address,
            "to": pair_addr,
            "data": "0xbc25cf77" + "0" * 24 + account.address[2:].lower().zfill(40),
        })
        print(f"  skim() gas estimate: {skim_gas}")
        if skim_gas > MAX_SKIM_GAS:
            print(f"  ABORT: skim() costs {skim_gas} gas (>{MAX_SKIM_GAS})")
            return False
    except Exception as e:
        print(f"  ABORT: skim() reverts on estimate ({str(e)[:80]})")
        return False

    # 5. Check ETH value
    eth_value = 0.0
    if token0.lower() == WETH.lower() and excess0 > 0:
        eth_value = float(Web3.from_wei(excess0, "ether"))
    elif token1.lower() == WETH.lower() and excess1 > 0:
        eth_value = float(Web3.from_wei(excess1, "ether"))
    print(f"  ETH value of excess: {eth_value:.6f} ETH")

    return True


def execute_skim(pair_address):
    pair_addr = Web3.to_checksum_address(pair_address)
    print(f"Preflight checks for {pair_addr}...")

    if not preflight(pair_addr):
        print("SKIM ABORTED — failed preflight")
        return

    print("Preflight PASSED — executing skim()...")
    pair = w3.eth.contract(address=pair_addr, abi=PAIR_ABI)

    # Use gas estimate + 20% buffer instead of hardcoded 150K
    skim_gas = w3.eth.estimate_gas({
        "from": account.address,
        "to": pair_addr,
        "data": "0xbc25cf77" + "0" * 24 + account.address[2:].lower().zfill(40),
    })
    gas_limit = int(skim_gas * 1.2)

    tx = pair.functions.skim(account.address).build_transaction({
        'from': account.address,
        'gas': gas_limit,
        'gasPrice': w3.eth.gas_price,
        'nonce': w3.eth.get_transaction_count(account.address),
    })

    signed = w3.eth.account.sign_transaction(tx, PRIVATE_KEY)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)

    status = "SUCCESS" if receipt['status'] == 1 else "FAILED"
    print(f"Skim tx: {tx_hash.hex()}")
    print(f"Status: {status}")
    print(f"Gas used: {receipt['gasUsed']} / {gas_limit}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 skim_executor.py <pair_address>")
        sys.exit(1)
    execute_skim(sys.argv[1])
