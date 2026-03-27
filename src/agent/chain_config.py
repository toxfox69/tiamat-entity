"""
Multi-chain configuration for TIAMAT scanner.
Etherscan V2 API key works across all chains via chainid parameter.
"""

CHAINS = {
    8453: {
        "name": "Base",
        "rpcs": [
            "https://base.drpc.org",
            "https://mainnet.base.org",
            "https://base-mainnet.public.blastapi.io",
            "https://1rpc.io/base",
        ],
        "ws": ["wss://base-mainnet.g.alchemy.com/v2/demo"],
        "weth": "0x4200000000000000000000000000000000000006",
        "block_time": 2,
        "auto_execute": True,
        "min_eth_value": 0.01,
        "factories": {
            "uniswap_v2": "0x8909Dc15e40173Ff4699343b6eB8132c65e18eC6",
            "aerodrome": "0x420DD381b31aEf6683db6B902084cB0FFECe40Da",
        },
    },
    42161: {
        "name": "Arbitrum",
        "rpcs": [
            "https://arb1.arbitrum.io/rpc",
            "https://arbitrum.drpc.org",
            "https://rpc.ankr.com/arbitrum",
        ],
        "ws": [],
        "weth": "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",
        "block_time": 0.25,
        "auto_execute": True,
        "min_eth_value": 0.01,
        "factories": {
            "uniswap_v2": "0xf1D7CC64Fb4452F05c498126312eBE29f30Fbcf9",
            "sushiswap": "0xc35DADB65012eC5796536bD9864eD8773aBc74C4",
        },
    },
    10: {
        "name": "Optimism",
        "rpcs": [
            "https://mainnet.optimism.io",
            "https://optimism.drpc.org",
            "https://rpc.ankr.com/optimism",
        ],
        "ws": [],
        "weth": "0x4200000000000000000000000000000000000006",
        "block_time": 2,
        "auto_execute": True,
        "min_eth_value": 0.01,
        "factories": {
            "uniswap_v2": "0x0c3c1c532F1e39EdF36BE9Fe0bE1410313E074Bf",
            "velodrome": "0x25CbdDb98b35ab1FF77defb1B7a12a9C17eFFEA0",
        },
    },
    1: {
        "name": "Ethereum",
        "rpcs": [
            "https://eth.drpc.org",
            "https://rpc.ankr.com/eth",
            "https://ethereum-rpc.publicnode.com",
        ],
        "ws": [],
        "weth": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
        "block_time": 12,
        "auto_execute": True,   # Funded 2026-03-19 — auto-execute with tight gas cap
        "min_eth_value": 0.05,  # Only execute if finding is worth 0.05+ ETH (~$125)
        "factories": {
            "uniswap_v2": "0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f",
            "sushiswap": "0xC0AEe478e3658e2610c5F7A4A2E1777cE9e4f2Ac",
        },
    },
    999: {
        "name": "Hyperliquid",
        "rpcs": [
            "https://rpc.hyperliquid.xyz/evm",
            "https://hyperliquid.drpc.org",
        ],
        "ws": [],
        "weth": "0xafBA95a4C2f25C9616f8e54F010DF304C059971C",  # WHYPE (Wrapped HYPE)
        "block_time": 2,
        "auto_execute": False,  # Scan-only — unfunded (0 HYPE for gas)
        "min_eth_value": 0.01,
        "factories": {},  # No V2 factories — Hyperliquid uses V3-style DEXes
        "v3_factories": {
            # Active V3-style router/factory contracts discovered via block scanning
            "hl_router": "0x8549fD7FFC092F8366e416E129a622EC060104ea",  # 49 calls/20 blocks, has swap()
            "hl_executor": "0x6131B5fae19EA4f9D964eAc0408E4408b66337b5",  # 13 calls/20 blocks
        },
    },
    # 4217: Tempo — DISABLED: returns fake ETH balances (4.2e57), spams garbage findings
    # Re-enable if Tempo gets a real ecosystem worth scanning
    # 4217: {
    #     "name": "Tempo",
    #     "rpcs": ["https://rpc.tempo.xyz", "https://tempo.drpc.org"],
    #     "ws": [],
    #     "weth": "0x20C000000000000000000000b9537d11c60E8b50",
    #     "block_time": 2,
    #     "auto_execute": False,
    #     "min_eth_value": 0.01,
    #     "factories": {
    #         "tempo_dex_0": "0x942Bd5BFdc5317C5507e326f8EB4BB6058AB5C10",
    #         "tempo_dex_1": "0x9C143b72254989eE952F3A1c73CFFfeC7C0e4a1A",
    #         "tempo_dex_2": "0x0C44525860Cc5fe8A75f4eAD9f1A54e532143bd3",
    #     },
    # },
}

# Wallet needs ETH on each chain to execute.
# For now, only Base is funded. Others are scan + alert only.
FUNDED_CHAINS = [8453, 1]  # Base + Ethereum mainnet (funded 2026-03-19)

def get_chain_config(chain_id):
    """Get config for a specific chain. Returns None if unknown."""
    return CHAINS.get(chain_id)

def get_findings_file(chain_id):
    return f"/root/.automaton/vuln_findings_{chain_id}.json"

def get_watched_pairs_file(chain_id):
    return f"/root/.automaton/watched_pairs_{chain_id}.json"
