"""
TIAMAT Base Chain Scanner
Reads on-chain data from Base network. READ-ONLY until creator approves trades.
"""
import json
from web3 import Web3

# Base chain RPCs (free, no API key)
BASE_RPCS = [
    "https://mainnet.base.org",
    "https://base.meowrpc.com",
    "https://base.drpc.org",
    "https://1rpc.io/base"
]

# Key DEX router addresses on Base
ADDRESSES = {
    "uniswap_v3_router": "0x2626664c2603336E57B271c5C0b26F421741e481",
    "aerodrome_router": "0xcF77a3Ba9A5CA399B7c97c74d54e5b1Beb874E43",
    "baseswap_router": "0x327Df1E6de05895d2ab08513aaDD9313Fe505d86",
    "sushiswap_router": "0xFB7eF66a7e61224DD6FcD0D7d9C3be5C8B049b9f",
    "USDC": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    "WETH": "0x4200000000000000000000000000000000000006",
    "DAI": "0x50c5725949A6F0c72E6C4a641F24049A917DB0Cb",
    "USDbC": "0xd9aAEc86B65D86f6A7B5B1b0c42FFA531710b6CA",
    "cbETH": "0x2Ae3F1Ec7F1F5012CFEab0185bfc7aa3cf0DEc22",
    "TOSHI": "0xAC1Bd2486aAf3B5C0fc3Fd868558b082a531B2B4",
    "BRETT": "0x532f27101965dd16442E59d40670FaF5eBB142E4",
    "DEGEN": "0x4ed4E862860beD51a9570b96d89aF5E1B0Efefed"
}

# Standard ERC20 ABI (just balanceOf and decimals)
ERC20_ABI = json.loads('[{"constant":true,"inputs":[{"name":"_owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"type":"function"},{"constant":true,"inputs":[],"name":"decimals","outputs":[{"name":"","type":"uint8"}],"type":"function"},{"constant":true,"inputs":[],"name":"symbol","outputs":[{"name":"","type":"string"}],"type":"function"}]')

# Uniswap V3 Quoter for price checks
QUOTER_ADDRESS = "0x3d4e44Eb1374240CE5F1B871ab261CD16335B76a"
QUOTER_ABI = json.loads('[{"inputs":[{"internalType":"address","name":"tokenIn","type":"address"},{"internalType":"address","name":"tokenOut","type":"address"},{"internalType":"uint24","name":"fee","type":"uint24"},{"internalType":"uint256","name":"amountIn","type":"uint256"},{"internalType":"uint160","name":"sqrtPriceLimitX96","type":"uint160"}],"name":"quoteExactInputSingle","outputs":[{"internalType":"uint256","name":"amountOut","type":"uint256"}],"stateMutability":"nonpayable","type":"function"}]')


class BaseScanner:
    def __init__(self):
        self.w3 = None
        self._connect()

    def _connect(self):
        for rpc in BASE_RPCS:
            try:
                w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 10}))
                if w3.is_connected():
                    self.w3 = w3
                    self.rpc = rpc
                    return
            except Exception:
                continue
        raise ConnectionError("All Base RPCs failed")

    def get_eth_balance(self, address):
        """Get ETH balance in human-readable format"""
        bal = self.w3.eth.get_balance(Web3.to_checksum_address(address))
        return self.w3.from_wei(bal, 'ether')

    def get_token_balance(self, token_address, wallet_address):
        """Get ERC20 token balance"""
        contract = self.w3.eth.contract(
            address=Web3.to_checksum_address(token_address),
            abi=ERC20_ABI
        )
        decimals = contract.functions.decimals().call()
        balance = contract.functions.balanceOf(
            Web3.to_checksum_address(wallet_address)
        ).call()
        symbol = contract.functions.symbol().call()
        return {"symbol": symbol, "balance": balance / (10 ** decimals), "raw": balance}

    def scan_wallet(self, address):
        """Full wallet scan - ETH + all known tokens"""
        results = {"address": address, "eth": float(self.get_eth_balance(address)), "tokens": []}
        for name, token_addr in ADDRESSES.items():
            if name.endswith("_router") or name == "WETH":
                continue
            try:
                info = self.get_token_balance(token_addr, address)
                if info["balance"] > 0:
                    results["tokens"].append({"name": name, **info})
            except Exception:
                pass
        return results

    def get_price_uniswap(self, token_in, token_out, amount_in, fee=3000):
        """Get quote from Uniswap V3 on Base"""
        quoter = self.w3.eth.contract(
            address=Web3.to_checksum_address(QUOTER_ADDRESS),
            abi=QUOTER_ABI
        )
        try:
            amount_out = quoter.functions.quoteExactInputSingle(
                Web3.to_checksum_address(token_in),
                Web3.to_checksum_address(token_out),
                fee,
                amount_in,
                0
            ).call()
            return amount_out
        except Exception:
            return None

    def find_arb_opportunity(self, token_a, token_b, amount):
        """
        Check price on Uniswap vs implied reverse price.
        Returns spread percentage. READ ONLY - does not trade.
        """
        # Price A->B on different fee tiers
        prices = {}
        for fee in [500, 3000, 10000]:
            quote = self.get_price_uniswap(token_a, token_b, amount, fee)
            if quote:
                prices[f"fee_{fee}"] = quote

        if len(prices) < 2:
            return None

        best = max(prices.values())
        worst = min(prices.values())
        spread_pct = ((best - worst) / worst) * 100

        return {
            "pair": f"{token_a[:8]}.../{token_b[:8]}...",
            "quotes_by_fee": prices,
            "best": best,
            "worst": worst,
            "spread_pct": round(spread_pct, 4),
            "profitable_after_gas": spread_pct > 0.3  # need >0.3% to cover gas
        }

    def scan_arb_opportunities(self):
        """Scan major pairs for arbitrage between fee tiers"""
        pairs = [
            (ADDRESSES["WETH"], ADDRESSES["USDC"], 10**17),      # 0.1 ETH
            (ADDRESSES["WETH"], ADDRESSES["DAI"], 10**17),       # 0.1 ETH
            (ADDRESSES["USDC"], ADDRESSES["USDbC"], 10**8),      # 100 USDC
            (ADDRESSES["WETH"], ADDRESSES["cbETH"], 10**17),     # 0.1 ETH
        ]

        opportunities = []
        for token_a, token_b, amount in pairs:
            result = self.find_arb_opportunity(token_a, token_b, amount)
            if result and result["spread_pct"] > 0.1:
                opportunities.append(result)

        return opportunities

    def scan_recent_transfers(self, address, blocks_back=2000):
        """Check recent ERC20 Transfer events TO this address.
        Uses small block range to stay within free RPC limits."""
        current_block = self.w3.eth.block_number
        # ERC20 Transfer event topic
        transfer_topic = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
        padded_addr = "0x" + address[2:].lower().zfill(64)

        # Try multiple RPCs if get_logs fails (some free RPCs block this)
        last_error = None
        logs = []
        for rpc in BASE_RPCS:
            try:
                w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 15}))
                if not w3.is_connected():
                    continue
                logs = w3.eth.get_logs({
                    "fromBlock": current_block - blocks_back,
                    "toBlock": "latest",
                    "topics": [transfer_topic, None, padded_addr]
                })
                break
            except Exception as e:
                last_error = e
                continue
        else:
            return {"error": f"All RPCs failed for get_logs: {last_error}"}

        transfers = []
        seen_tokens = set()
        for log in logs:
            token_addr = log["address"]
            if token_addr in seen_tokens:
                continue
            seen_tokens.add(token_addr)
            try:
                info = self.get_token_balance(token_addr, address)
                if info["balance"] > 0:
                    transfers.append({
                        "token": token_addr,
                        "symbol": info["symbol"],
                        "current_balance": info["balance"],
                        "tx": log["transactionHash"].hex(),
                        "block": log["blockNumber"]
                    })
            except Exception:
                transfers.append({"token": token_addr, "tx": log["transactionHash"].hex()})

        return transfers

    def check_pending_txs(self, address):
        """Check if wallet has any stuck/pending transactions"""
        nonce_latest = self.w3.eth.get_transaction_count(
            Web3.to_checksum_address(address), "latest"
        )
        nonce_pending = self.w3.eth.get_transaction_count(
            Web3.to_checksum_address(address), "pending"
        )
        return {
            "confirmed_nonce": nonce_latest,
            "pending_nonce": nonce_pending,
            "stuck_txs": nonce_pending - nonce_latest
        }
