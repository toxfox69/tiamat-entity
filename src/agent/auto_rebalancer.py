#!/usr/bin/env python3
"""
Auto-rebalancer for TIAMAT's multi-chain wallet.
Maintains minimum gas balances across all active chains.
Uses LI.FI API for swaps and bridges — free, no API key.

Flow:
1. Check balances on all chains
2. If any chain is below minimum, find the best funded source
3. Swap/bridge from source -> underfunded chain
4. Verify arrival
5. Log everything, Telegram alert on every tx

Safety: Only moves funds between TIAMAT's own wallet on different chains.
Never sends to any external address.
"""

import os
import sys
import json
import time
import logging
import requests
import fcntl
from web3 import Web3
from dotenv import load_dotenv

load_dotenv('/root/.env')
sys.path.insert(0, os.path.dirname(__file__))

LOG_FILE = "/root/.automaton/rebalancer.log"
EXEC_LOG = "/root/.automaton/execution_log.json"
STATE_FILE = "/root/.automaton/rebalancer_state.json"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [REBALANCE] %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
log = logging.getLogger('rebalancer')

WALLET_ADDR = "0xdc118c4e1284a61e4d5277936a64B9E08Ad9e7EE"
WALLET_KEY = os.environ.get("TIAMAT_WALLET_KEY")

LIFI_API = "https://li.quest/v1"

# ==========================================
# CHAIN CONFIGURATION
# ==========================================

CHAINS = {
    8453: {
        "name": "Base",
        "rpcs": ["https://mainnet.base.org", "https://base.meowrpc.com"],
        "min_eth": 0.001,      # ~$2.50 — enough for hundreds of Base txns
        "target_eth": 0.002,   # Top up to this amount
        "is_source": True,     # Can bridge FROM this chain (has USDC)
        "usdc_address": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
        "usdc_decimals": 6,
    },
    42161: {
        "name": "Arbitrum",
        "rpcs": ["https://arb1.arbitrum.io/rpc", "https://arbitrum.drpc.org"],
        "min_eth": 0.0008,     # ~$2 — Arbitrum gas is very cheap
        "target_eth": 0.002,
        "is_source": False,
        "usdc_address": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
        "usdc_decimals": 6,
    },
    10: {
        "name": "Optimism",
        "rpcs": ["https://mainnet.optimism.io", "https://optimism.drpc.org"],
        "min_eth": 0.001,      # ~$2.50 — similar to Base
        "target_eth": 0.002,
        "is_source": False,
        "usdc_address": "0x0b2C639c533813f4Aa9D7837CAf62653d097Ff85",
        "usdc_decimals": 6,
    },
    1: {
        "name": "Ethereum",
        "rpcs": ["https://eth.drpc.org", "https://rpc.ankr.com/eth"],
        "min_eth": 0.005,      # ~$12.50 — mainnet gas is expensive
        "target_eth": 0.01,
        "is_source": False,
        "usdc_address": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
        "usdc_decimals": 6,
    },
}

ETH_NATIVE = "0x0000000000000000000000000000000000000000"

# ==========================================
# BALANCE CHECKING
# ==========================================

def get_eth_balance(chain_id):
    """Get ETH balance on a specific chain."""
    config = CHAINS[chain_id]
    w3 = Web3(Web3.HTTPProvider(config["rpcs"][0]))
    addr = Web3.to_checksum_address(WALLET_ADDR)
    return float(w3.from_wei(w3.eth.get_balance(addr), 'ether'))


def get_usdc_balance(chain_id):
    """Get USDC balance on a specific chain."""
    config = CHAINS[chain_id]
    w3 = Web3(Web3.HTTPProvider(config["rpcs"][0]))
    addr = Web3.to_checksum_address(WALLET_ADDR)
    usdc = Web3.to_checksum_address(config["usdc_address"])

    # balanceOf(address)
    data = '0x70a08231' + addr.lower()[2:].zfill(64)
    try:
        result = w3.eth.call({'to': usdc, 'data': data})
        raw_balance = int.from_bytes(result, 'big')
        return raw_balance / (10 ** config["usdc_decimals"])
    except:
        return 0.0


def check_all_balances():
    """Check ETH and USDC balances on all chains."""
    balances = {}
    for chain_id, config in CHAINS.items():
        try:
            eth = get_eth_balance(chain_id)
            usdc = get_usdc_balance(chain_id)
            below_min = eth < config["min_eth"]
            balances[chain_id] = {
                "name": config["name"],
                "eth": eth,
                "usdc": usdc,
                "min_eth": config["min_eth"],
                "target_eth": config["target_eth"],
                "below_minimum": below_min,
                "needs_topup": config["target_eth"] - eth if below_min else 0,
            }
        except Exception as e:
            balances[chain_id] = {
                "name": config["name"],
                "error": str(e)[:100]
            }
    return balances


# ==========================================
# LI.FI INTEGRATION — SWAP + BRIDGE
# ==========================================

def get_lifi_quote(from_chain, to_chain, from_token, to_token, amount_raw):
    """
    Get a swap/bridge quote from LI.FI.
    Returns the full quote including transaction to sign.
    """
    # LI.FI requires lowercase addresses (rejects mixed-case EIP-55 checksums)
    wallet_lower = WALLET_ADDR.lower()
    params = {
        "fromChain": str(from_chain),
        "toChain": str(to_chain),
        "fromToken": from_token,
        "toToken": to_token,
        "fromAmount": str(amount_raw),
        "fromAddress": wallet_lower,
        "toAddress": wallet_lower,  # ALWAYS same wallet
        "slippage": "0.03",  # 3% slippage tolerance
        "allowBridges": "across,stargate,hop,cbridge",  # Trusted bridges only
    }

    try:
        resp = requests.get(f"{LIFI_API}/quote", params=params, timeout=30)
        if resp.status_code == 200:
            return resp.json()
        else:
            log.error(f"LI.FI quote failed: {resp.status_code} — {resp.text[:200]}")
            return None
    except Exception as e:
        log.error(f"LI.FI request failed: {str(e)[:150]}")
        return None


def check_lifi_status(tx_hash, from_chain):
    """Check bridge transaction status."""
    try:
        resp = requests.get(f"{LIFI_API}/status", params={
            "txHash": tx_hash,
            "fromChain": str(from_chain),
        }, timeout=15)
        if resp.status_code == 200:
            return resp.json()
    except:
        pass
    return None


def execute_lifi_tx(quote, chain_id):
    """
    Sign and send the transaction from a LI.FI quote.
    The quote contains a ready-to-sign transactionRequest.
    """
    if not WALLET_KEY:
        log.error("No wallet key — cannot execute")
        return None

    tx_request = quote.get("transactionRequest", {})
    if not tx_request:
        log.error("Quote has no transactionRequest")
        return None

    config = CHAINS[chain_id]
    w3 = Web3(Web3.HTTPProvider(config["rpcs"][0]))
    account = w3.eth.account.from_key(WALLET_KEY)
    wallet = Web3.to_checksum_address(WALLET_ADDR)

    try:
        # Build transaction from LI.FI's response
        raw_value = tx_request.get('value', '0')
        if isinstance(raw_value, str) and raw_value.startswith('0x'):
            value = int(raw_value, 16)
        else:
            value = int(raw_value)

        tx = {
            'to': Web3.to_checksum_address(tx_request['to']),
            'data': tx_request['data'],
            'value': value,
            'nonce': w3.eth.get_transaction_count(wallet),
            'chainId': chain_id,
        }

        # Gas: use LI.FI's estimate or calculate our own
        if 'gasLimit' in tx_request:
            raw_gas = tx_request['gasLimit']
            gas_limit = int(raw_gas, 16) if isinstance(raw_gas, str) and raw_gas.startswith('0x') else int(raw_gas)
            tx['gas'] = gas_limit
        else:
            tx['gas'] = 300000  # Safe default for bridge txs

        # EIP-1559 gas
        if 'gasPrice' in tx_request:
            raw_gp = tx_request['gasPrice']
            tx['gasPrice'] = int(raw_gp, 16) if isinstance(raw_gp, str) and raw_gp.startswith('0x') else int(raw_gp)
        else:
            block = w3.eth.get_block('latest')
            base_fee = block.get('baseFeePerGas', Web3.to_wei(1, 'gwei'))
            tx['maxFeePerGas'] = min(base_fee * 2, Web3.to_wei(100, 'gwei'))
            tx['maxPriorityFeePerGas'] = Web3.to_wei(0.1, 'gwei')

        # Safety check: never send more than ~$25 worth of value in a rebalance
        value_eth = float(Web3.from_wei(tx['value'], 'ether'))
        if value_eth > 0.01:
            log.warning(f"Rebalance tx value too high: {value_eth} ETH — aborting")
            _telegram(f"⚠️ Rebalance ABORTED: tx value {value_eth} ETH exceeds safety limit")
            return None

        # USDC approval may be needed first
        # LI.FI tells us in the quote if approval is needed
        approval_data = quote.get("approvalData")
        if approval_data:
            approve_to = Web3.to_checksum_address(approval_data['approvalAddress'])
            approve_tx = {
                'to': Web3.to_checksum_address(config["usdc_address"]),
                'data': _build_approve_data(approve_to, approval_data.get('amount')),
                'nonce': w3.eth.get_transaction_count(wallet),
                'gas': 60000,
                'chainId': chain_id,
            }
            block = w3.eth.get_block('latest')
            base_fee = block.get('baseFeePerGas', Web3.to_wei(1, 'gwei'))
            approve_tx['maxFeePerGas'] = min(base_fee * 2, Web3.to_wei(100, 'gwei'))
            approve_tx['maxPriorityFeePerGas'] = Web3.to_wei(0.1, 'gwei')

            signed_approve = account.sign_transaction(approve_tx)
            approve_hash = w3.eth.send_raw_transaction(signed_approve.raw_transaction)
            log.info(f"USDC Approval TX: {approve_hash.hex()}")
            w3.eth.wait_for_transaction_receipt(approve_hash, timeout=30)

            # Update nonce for the actual bridge tx
            tx['nonce'] = w3.eth.get_transaction_count(wallet)

        # Sign and send the bridge/swap tx
        signed = account.sign_transaction(tx)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        tx_hex = tx_hash.hex()

        log.info(f"REBALANCE TX SENT: {tx_hex}")

        # Wait for receipt on source chain
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)

        if receipt['status'] == 1:
            log.info(f"REBALANCE TX CONFIRMED: {tx_hex}")
            return tx_hex
        else:
            log.error(f"REBALANCE TX REVERTED: {tx_hex}")
            return None

    except Exception as e:
        log.error(f"REBALANCE TX FAILED: {str(e)[:200]}")
        _telegram(f"❌ Rebalance TX failed: {str(e)[:100]}")
        return None


def _build_approve_data(spender, amount=None):
    """Build ERC20 approve(spender, amount) calldata."""
    if amount is None:
        amount_hex = "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
    elif isinstance(amount, str) and amount.startswith("0x"):
        amount_hex = amount[2:].zfill(64)
    else:
        amount_hex = hex(int(amount))[2:].zfill(64)

    spender_hex = spender.lower()[2:].zfill(64)
    return "0x095ea7b3" + spender_hex + amount_hex


# ==========================================
# AUTO-REBALANCE LOGIC
# ==========================================

def find_best_source(target_chain_id, amount_eth_needed):
    """
    Find the best chain to fund from.
    Priority: USDC on Base > ETH excess on any chain
    """
    sources = []

    for chain_id, config in CHAINS.items():
        if chain_id == target_chain_id:
            continue

        try:
            eth_bal = get_eth_balance(chain_id)
            usdc_bal = get_usdc_balance(chain_id)

            # Has USDC? Best source — no need to touch ETH reserves
            if usdc_bal >= 1.0:  # At least $1 USDC
                sources.append({
                    "chain_id": chain_id,
                    "name": config["name"],
                    "method": "usdc_to_eth",
                    "usdc_available": usdc_bal,
                    "eth_available": eth_bal,
                    "priority": 1,  # Highest priority — use USDC first
                })

            # Has excess ETH? (more than target + buffer)
            excess = eth_bal - config["target_eth"] - 0.001  # Keep buffer
            if excess > amount_eth_needed:
                sources.append({
                    "chain_id": chain_id,
                    "name": config["name"],
                    "method": "eth_bridge",
                    "excess_eth": excess,
                    "eth_available": eth_bal,
                    "priority": 2,  # Second priority — bridge ETH
                })
        except:
            continue

    # Sort by priority (USDC first, then ETH)
    sources.sort(key=lambda x: x["priority"])
    return sources[0] if sources else None


def rebalance_chain(target_chain_id):
    """
    Top up a chain that's below minimum balance.
    1. Find best funding source
    2. Get LI.FI quote
    3. Execute swap/bridge
    4. Wait and verify
    """
    config = CHAINS[target_chain_id]
    current_eth = get_eth_balance(target_chain_id)
    needed = config["target_eth"] - current_eth

    if needed <= 0:
        log.info(f"{config['name']} doesn't need rebalancing (has {current_eth:.6f} ETH)")
        return True

    log.info(f"{config['name']} needs {needed:.6f} ETH (has {current_eth:.6f}, target {config['target_eth']})")

    # Find source
    source = find_best_source(target_chain_id, needed)
    if not source:
        log.warning(f"No funding source available for {config['name']}")
        _telegram(f"⚠️ Cannot rebalance {config['name']} — no source has enough funds")
        return False

    log.info(f"Best source: {source['name']} via {source['method']}")

    quote = None
    amount_moved = 0

    if source["method"] == "usdc_to_eth":
        # Calculate USDC amount needed (~$2-5 worth to cover target ETH)
        # Rough: 1 ETH ~ $2500, so target_eth * 2800 (buffer for slippage + fees)
        usdc_amount = needed * 2800
        usdc_amount = min(usdc_amount, source["usdc_available"] * 0.9)  # Don't drain source
        usdc_amount = max(usdc_amount, 1.0)  # Minimum $1
        usdc_raw = int(usdc_amount * 10**6)  # USDC has 6 decimals
        amount_moved = usdc_amount

        from_token = CHAINS[source["chain_id"]]["usdc_address"]
        to_token = ETH_NATIVE

        log.info(f"Swapping {usdc_amount:.2f} USDC on {source['name']} -> ETH on {config['name']}")
        _telegram(f"🔄 Rebalancing: {usdc_amount:.2f} USDC ({source['name']}) -> ETH ({config['name']})")

        quote = get_lifi_quote(
            from_chain=source["chain_id"],
            to_chain=target_chain_id,
            from_token=from_token,
            to_token=to_token,
            amount_raw=usdc_raw
        )

    elif source["method"] == "eth_bridge":
        # Bridge ETH directly
        bridge_amount = min(needed * 1.1, source["excess_eth"])  # 10% buffer
        amount_raw = int(bridge_amount * 10**18)  # ETH has 18 decimals
        amount_moved = bridge_amount

        log.info(f"Bridging {bridge_amount:.6f} ETH from {source['name']} -> {config['name']}")
        _telegram(f"🌉 Bridging: {bridge_amount:.6f} ETH ({source['name']} -> {config['name']})")

        quote = get_lifi_quote(
            from_chain=source["chain_id"],
            to_chain=target_chain_id,
            from_token=ETH_NATIVE,
            to_token=ETH_NATIVE,
            amount_raw=amount_raw
        )

    if not quote:
        log.error("Failed to get LI.FI quote")
        _telegram(f"❌ Rebalance failed: no quote from LI.FI for {config['name']}")
        return False

    # Log the quote details
    estimate = quote.get("estimate", {})
    to_amount = estimate.get("toAmount", "0")
    to_eth = float(to_amount) / 10**18 if to_amount else 0
    duration = estimate.get("executionDuration", "unknown")

    log.info(f"Quote: receive ~{to_eth:.6f} ETH, duration ~{duration}s")

    # Safety: check that we're receiving a reasonable amount
    if to_eth < needed * 0.5:  # If we'd receive less than half of what we need, bad quote
        log.warning(f"Bad quote: expected ~{needed:.6f} ETH, would receive {to_eth:.6f}")
        _telegram(f"⚠️ Rebalance: bad quote for {config['name']}. Need {needed:.6f}, would get {to_eth:.6f}")
        return False

    # Execute
    tx_hash = execute_lifi_tx(quote, source["chain_id"])
    if not tx_hash:
        return False

    # Log
    _log_exec(source["chain_id"], target_chain_id, tx_hash, source["method"], amount_moved)

    # Wait for destination chain to receive funds
    log.info(f"Waiting for funds on {config['name']}...")
    _telegram(f"⏳ Waiting for {config['name']} to receive funds (tx: {tx_hash[:16]}...)")

    for i in range(12):  # Wait up to 2 minutes
        time.sleep(10)
        new_bal = get_eth_balance(target_chain_id)
        if new_bal > current_eth + (needed * 0.3):  # At least 30% arrived
            log.info(f"Funds arrived on {config['name']}: {new_bal:.6f} ETH")
            _telegram(f"✅ Rebalance complete: {config['name']} now has {new_bal:.6f} ETH")
            return True

    log.warning(f"Funds may still be bridging to {config['name']} — check later")
    _telegram(f"⏱️ Bridge may still be processing for {config['name']}. Check in a few minutes.")
    return True  # Don't retry, bridge might just be slow


def run_rebalance_check():
    """
    Main rebalance routine. Check all chains, top up any that are low.
    Call this every 500 cycles or as a cooldown task.
    """
    log.info("=" * 50)
    log.info("REBALANCE CHECK STARTING")

    balances = check_all_balances()

    # Print status
    for chain_id, bal in balances.items():
        if "error" in bal:
            log.error(f"  {bal.get('name', chain_id)}: ERROR — {bal['error']}")
            continue
        status = "LOW" if bal["below_minimum"] else "OK"
        log.info(f"  {bal['name']:12}: {bal['eth']:.6f} ETH | {bal['usdc']:.2f} USDC | min: {bal['min_eth']} | {status}")

    # Find chains that need topping up
    needs_funding = [
        (cid, bal) for cid, bal in balances.items()
        if bal.get("below_minimum") and "error" not in bal
    ]

    if not needs_funding:
        log.info("All chains adequately funded. No rebalancing needed.")
        return True

    log.info(f"{len(needs_funding)} chain(s) need rebalancing")

    success = True
    for chain_id, bal in needs_funding:
        # Skip Ethereum mainnet auto-rebalancing — gas too expensive
        if chain_id == 1:
            log.info(f"Skipping Ethereum mainnet auto-rebalance (manual only)")
            _telegram(f"ℹ️ Ethereum mainnet is low ({bal['eth']:.6f} ETH) but auto-rebalance disabled. Fund manually if needed.")
            continue

        result = rebalance_chain(chain_id)
        if not result:
            success = False

    log.info("REBALANCE CHECK COMPLETE")
    log.info("=" * 50)
    return success


# ==========================================
# LOGGING AND ALERTS
# ==========================================

def _log_exec(from_chain, to_chain, tx_hash, method, amount):
    entry = json.dumps({
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": "rebalancer",
        "action": "rebalance",
        "from_chain": CHAINS[from_chain]["name"],
        "to_chain": CHAINS[to_chain]["name"],
        "method": method,
        "amount": amount,
        "tx_hash": tx_hash,
    })
    try:
        with open(EXEC_LOG, 'a') as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            f.write(entry + '\n')
            fcntl.flock(f, fcntl.LOCK_UN)
    except:
        pass


def _telegram(message):
    try:
        token = os.environ.get("TELEGRAM_BOT_TOKEN")
        chat_id = os.environ.get("TELEGRAM_CHAT_ID")
        if token and chat_id:
            requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": message},
                timeout=5
            )
    except:
        pass


# ==========================================
# CLI + ENTRY POINTS
# ==========================================

def print_status():
    """Print current balances and rebalancing needs."""
    print(f"\nWallet: {WALLET_ADDR}")
    print("=" * 60)

    balances = check_all_balances()
    total_eth = 0
    total_usdc = 0

    for chain_id, bal in balances.items():
        if "error" in bal:
            print(f"  {bal.get('name', chain_id):12}: ERROR — {bal['error']}")
            continue

        status = "NEEDS TOPUP" if bal["below_minimum"] else "OK"
        print(f"  {bal['name']:12}: {bal['eth']:.6f} ETH | {bal['usdc']:.2f} USDC | min: {bal['min_eth']:.4f} | {status}")
        total_eth += bal['eth']
        total_usdc += bal['usdc']

    print("=" * 60)
    print(f"  {'TOTAL':12}: {total_eth:.6f} ETH | {total_usdc:.2f} USDC")

    needs = [b for b in balances.values() if b.get("below_minimum")]
    if needs:
        print(f"\n  {len(needs)} chain(s) below minimum — run 'rebalance' to fix")
    else:
        print(f"\n  All chains funded")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python3 auto_rebalancer.py status     — show all balances")
        print("  python3 auto_rebalancer.py rebalance  — auto-rebalance low chains")
        print("  python3 auto_rebalancer.py test       — test LI.FI API connectivity")
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "status":
        print_status()

    elif cmd == "rebalance":
        run_rebalance_check()

    elif cmd == "test":
        # Test LI.FI API
        print("Testing LI.FI API...")
        try:
            r = requests.get(f"{LIFI_API}/chains", timeout=10)
            chains = r.json().get("chains", [])
            supported = [c["name"] for c in chains if c.get("id") in [8453, 42161, 10, 1]]
            print(f"  LI.FI API: OK")
            print(f"  Supported chains: {', '.join(supported)}")
        except Exception as e:
            print(f"  LI.FI API: FAIL — {str(e)[:100]}")

        # Test a quote (don't execute)
        print("\nTesting quote: 2 USDC (Base) -> ETH (Arbitrum)...")
        quote = get_lifi_quote(
            from_chain=8453,
            to_chain=42161,
            from_token="0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
            to_token=ETH_NATIVE,
            amount_raw=2000000  # 2 USDC
        )
        if quote:
            est = quote.get("estimate", {})
            to_amt = float(est.get("toAmount", 0)) / 10**18
            dur = est.get("executionDuration", "?")
            print(f"  Quote: receive ~{to_amt:.6f} ETH, duration ~{dur}s")
        else:
            print(f"  Quote: FAILED")

    else:
        print(f"Unknown command: {cmd}")
