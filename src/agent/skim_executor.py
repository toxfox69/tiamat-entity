#!/usr/bin/env python3
"""
Execute skim() on Uniswap V2 pairs with excess tokens.
Usage: python3 skim_executor.py <pair_address>
"""
import sys
import json
import time
import os
from web3 import Web3
from web3.middleware import geth_poa_middleware
from eth_account import Account

PRIVATE_KEY = os.environ.get("TIAMAT_WALLET_KEY")
if not PRIVATE_KEY:
    print("Set TIAMAT_WALLET_KEY in /root/.env")
    sys.exit(1)

account = Account.from_key(PRIVATE_KEY)
w3 = Web3(Web3.HTTPProvider("https://base.drpc.org"))
w3.middleware_onion.inject(geth_poa_middleware, layer=0)

PAIR_ABI = json.loads("""[
{"constant":false,"inputs":[{"name":"to","type":"address"}],"name":"skim","outputs":[],"type":"function"},
{"constant":true,"inputs":[],"name":"getReserves","outputs":[{"name":"","type":"uint112"},{"name":"","type":"uint112"},{"name":"","type":"uint32"}],"type":"function"}
]""")

def execute_skim(pair_address):
    pair = w3.eth.contract(
        address=Web3.to_checksum_address(pair_address),
        abi=PAIR_ABI
    )

    tx = pair.functions.skim(account.address).build_transaction({
        'from': account.address,
        'gas': 150_000,
        'gasPrice': w3.eth.gas_price,
        'nonce': w3.eth.get_transaction_count(account.address),
    })

    signed = w3.eth.account.sign_transaction(tx, PRIVATE_KEY)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)

    print(f"Skim tx: {tx_hash.hex()}")
    print(f"Status: {'SUCCESS' if receipt['status'] == 1 else 'FAILED'}")
    print(f"Gas used: {receipt['gasUsed']}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 skim_executor.py <pair_address>")
        sys.exit(1)
    execute_skim(sys.argv[1])
