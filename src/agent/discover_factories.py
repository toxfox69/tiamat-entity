#!/usr/bin/env python3
"""
DEX Factory Discovery — scan any EVM chain for Uniswap V2-style factories.
Finds PairCreated events in recent blocks, groups by emitting contract (= factory),
and discovers WETH by token frequency analysis.

Usage:
    python3 discover_factories.py --rpc https://rpc.hyperliquid.xyz/evm --blocks 10000
    python3 discover_factories.py --rpc https://rpc.tempo.xyz --blocks 10000
"""

import argparse
import json
import sys
from collections import Counter
from web3 import Web3

PAIR_CREATED_TOPIC = "0x" + Web3.keccak(
    text="PairCreated(address,address,address,uint256)"
).hex()


def discover(rpc_url, num_blocks=10000, batch_size=2000):
    w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 30}))
    if not w3.is_connected():
        print(f"ERROR: Cannot connect to {rpc_url}")
        sys.exit(1)

    chain_id = w3.eth.chain_id
    current_block = w3.eth.block_number
    from_block = max(0, current_block - num_blocks)

    print(f"Chain ID: {chain_id}")
    print(f"Current block: {current_block}")
    print(f"Scanning blocks {from_block} - {current_block} ({num_blocks} blocks)")
    print(f"Looking for PairCreated events...")
    print()

    # Scan in batches to avoid RPC limits
    factories = Counter()
    token_freq = Counter()
    total_events = 0

    for start in range(from_block, current_block + 1, batch_size):
        end = min(start + batch_size - 1, current_block)
        try:
            logs = w3.eth.get_logs({
                "fromBlock": start,
                "toBlock": end,
                "topics": [PAIR_CREATED_TOPIC],
            })
            for log_entry in logs:
                factory = log_entry["address"]
                factories[factory] += 1
                total_events += 1

                # Extract token0 and token1 from topics
                if len(log_entry["topics"]) >= 3:
                    token0 = "0x" + log_entry["topics"][1].hex()[-40:]
                    token1 = "0x" + log_entry["topics"][2].hex()[-40:]
                    token_freq[token0.lower()] += 1
                    token_freq[token1.lower()] += 1

            if logs:
                print(f"  Blocks {start}-{end}: {len(logs)} PairCreated events")
        except Exception as e:
            err = str(e)[:100]
            if "exceed" in err.lower() or "limit" in err.lower():
                # Try smaller batches
                for sub_start in range(start, end + 1, batch_size // 5):
                    sub_end = min(sub_start + batch_size // 5 - 1, end)
                    try:
                        logs = w3.eth.get_logs({
                            "fromBlock": sub_start,
                            "toBlock": sub_end,
                            "topics": [PAIR_CREATED_TOPIC],
                        })
                        for log_entry in logs:
                            factory = log_entry["address"]
                            factories[factory] += 1
                            total_events += 1
                            if len(log_entry["topics"]) >= 3:
                                token0 = "0x" + log_entry["topics"][1].hex()[-40:]
                                token1 = "0x" + log_entry["topics"][2].hex()[-40:]
                                token_freq[token0.lower()] += 1
                                token_freq[token1.lower()] += 1
                    except Exception:
                        continue
            else:
                print(f"  Blocks {start}-{end}: ERROR — {err}")

    print(f"\nTotal PairCreated events: {total_events}")

    if not factories:
        print("\nNo factories found. This chain may not have V2-style DEXes yet.")
        return {"chain_id": chain_id, "factories": {}, "weth_candidate": None}

    # Report factories
    print(f"\nFactories found ({len(factories)}):")
    factory_list = {}
    for addr, count in factories.most_common(20):
        checksum = Web3.to_checksum_address(addr)
        print(f"  {checksum}: {count} pairs")
        factory_list[f"factory_{len(factory_list)}"] = checksum

    # WETH discovery: most-frequent token across all pairs = likely WETH
    weth_candidate = None
    if token_freq:
        top_token, top_count = token_freq.most_common(1)[0]
        weth_candidate = Web3.to_checksum_address(top_token)
        print(f"\nWETH candidate (most frequent token): {weth_candidate} ({top_count} appearances)")
        print("Top 5 tokens by frequency:")
        for tok, cnt in token_freq.most_common(5):
            print(f"  {Web3.to_checksum_address(tok)}: {cnt}")

    result = {
        "chain_id": chain_id,
        "rpc": rpc_url,
        "blocks_scanned": num_blocks,
        "total_pairs": total_events,
        "factories": factory_list,
        "weth_candidate": weth_candidate,
    }

    print(f"\n--- Config snippet for chain_config.py ---")
    print(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Discover DEX factories on any EVM chain")
    parser.add_argument("--rpc", required=True, help="RPC URL")
    parser.add_argument("--blocks", type=int, default=10000, help="Number of recent blocks to scan")
    parser.add_argument("--batch", type=int, default=2000, help="Batch size for log queries")
    args = parser.parse_args()

    discover(args.rpc, args.blocks, args.batch)
