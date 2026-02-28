"""
TIAMAT Contract Vulnerability Scanner — Multi-Chain
Read-only security scanner for responsible disclosure and Immunefi bounty research.
Detects: stuck ETH, skimmable pairs, dead proxies, unguarded functions,
uninitialized proxies, stuck trading fees.

Now with Etherscan V2 enrichment: verified source code analysis, deployer reputation,
and ABI-based function identification instead of blind bytecode guessing.

Supports: Base, Arbitrum, Optimism, Ethereum (via chain_config.py).

All findings are logged — NO exploitation, NO execution of vulnerable functions.
"""
import json
import sys
import time
import logging
from datetime import datetime, timezone
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

try:
    from etherscan_v2 import enrich_finding as etherscan_enrich
    HAS_ETHERSCAN = True
except ImportError:
    HAS_ETHERSCAN = False

try:
    from chain_config import CHAINS, get_findings_file
except ImportError:
    CHAINS = {}
    def get_findings_file(chain_id):
        return "/root/.automaton/vuln_findings.json"

# ── Config (defaults for Base, overridden by chain_config) ──

BASE_RPCS = [
    "https://base.drpc.org",
    "https://mainnet.base.org",
    "https://base-mainnet.public.blastapi.io",
    "https://1rpc.io/base",
]

FINDINGS_FILE = "/root/.automaton/vuln_findings.json"
SCAN_LOG = "/root/.automaton/vuln_scan.log"

# Key addresses (defaults for Base)
WETH = "0x4200000000000000000000000000000000000006"
DEAD_ADDRESSES = {
    "0x0000000000000000000000000000000000000000",
    "0x000000000000000000000000000000000000dEaD",
    "0x0000000000000000000000000000000000000001",
}

# Uniswap V2 factory on Base (backward compat)
UNISWAP_V2_FACTORY = "0x8909Dc15e40173Ff4699343b6eB8132c65e18eC6"
# Aerodrome factory on Base
AERODROME_FACTORY = "0x420DD381b31aEf6683db6B902084cB0FFECe40Da"

# ── ABIs ──

ERC20_ABI = json.loads(
    '[{"constant":true,"inputs":[{"name":"_owner","type":"address"}],'
    '"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],'
    '"type":"function"},{"constant":true,"inputs":[],"name":"decimals",'
    '"outputs":[{"name":"","type":"uint8"}],"type":"function"},'
    '{"constant":true,"inputs":[],"name":"symbol",'
    '"outputs":[{"name":"","type":"string"}],"type":"function"}]'
)

PAIR_ABI = json.loads(json.dumps([
    {"constant": True, "inputs": [], "name": "getReserves",
     "outputs": [
         {"name": "_reserve0", "type": "uint112"},
         {"name": "_reserve1", "type": "uint112"},
         {"name": "_blockTimestampLast", "type": "uint32"}
     ], "type": "function"},
    {"constant": True, "inputs": [], "name": "token0",
     "outputs": [{"name": "", "type": "address"}], "type": "function"},
    {"constant": True, "inputs": [], "name": "token1",
     "outputs": [{"name": "", "type": "address"}], "type": "function"},
    {"constant": True, "inputs": [{"name": "_owner", "type": "address"}],
     "name": "balanceOf",
     "outputs": [{"name": "balance", "type": "uint256"}], "type": "function"},
]))

FACTORY_ABI = json.loads(json.dumps([
    {"constant": True, "inputs": [], "name": "allPairsLength",
     "outputs": [{"name": "", "type": "uint256"}], "type": "function"},
    {"constant": True, "inputs": [{"name": "", "type": "uint256"}],
     "name": "allPairs",
     "outputs": [{"name": "", "type": "address"}], "type": "function"},
]))

# EIP-1967 implementation slot
EIP1967_IMPL_SLOT = "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc"

# Function selectors to check for unguarded functions
DANGEROUS_SELECTORS = {
    "0x3ccfd60b": "withdraw()",
    "0x51cff8d9": "withdraw(address)",
    "0x2e1a7d4d": "withdraw(uint256)",
    "0xf2fde38b": "transferOwnership(address)",
    "0x01681a62": "sweep(address)",
    "0xe9fad8ee": "exit()",
    "0x7b103999": "claimReward()",
    "0x853828b6": "withdrawAll()",
}

# Selectors that take no args — just the 4-byte selector
NO_ARG_SELECTORS = {"0x3ccfd60b", "0xe9fad8ee", "0x7b103999", "0x853828b6"}
# Selectors that take a single address arg
ADDR_ARG_SELECTORS = {"0x51cff8d9", "0xf2fde38b", "0x01681a62"}
# Selectors that take a single uint256 arg
UINT_ARG_SELECTORS = {"0x2e1a7d4d"}

# Random non-privileged caller for simulation (not owner, not zero)
SIM_CALLER = "0xDeaDbeefdEAdbeefdEadbEEFdeadbeEFdEaDbeeF"

# ── Logging ──

log = logging.getLogger("vuln_scanner")
if not log.handlers:
    log.setLevel(logging.INFO)
    _fmt = logging.Formatter("[%(asctime)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    _fh = logging.FileHandler(SCAN_LOG)
    _fh.setFormatter(_fmt)
    log.addHandler(_fh)
    log.propagate = False


class ContractScanner:
    def __init__(self, chain_id=8453, rpcs=None, weth=None, findings_file=None, chain_name=None):
        self.chain_id = chain_id
        self.chain_name = chain_name or "Base"
        self.rpcs = rpcs or BASE_RPCS
        self.weth = weth or WETH
        self.findings_file = findings_file or get_findings_file(chain_id)
        self.w3 = None
        self.rpc = None
        self.findings = []
        self._connect()

    @classmethod
    def from_chain_config(cls, chain_id):
        """Create a scanner from chain_config.py settings."""
        cfg = CHAINS.get(chain_id)
        if not cfg:
            raise ValueError(f"Unknown chain_id: {chain_id}")
        return cls(
            chain_id=chain_id,
            rpcs=cfg["rpcs"],
            weth=cfg["weth"],
            findings_file=get_findings_file(chain_id),
            chain_name=cfg["name"],
        )

    def _connect(self):
        for rpc in self.rpcs:
            try:
                w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 15}))
                w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
                if w3.is_connected():
                    self.w3 = w3
                    self.rpc = rpc
                    log.info(f"[{self.chain_name}] Connected to {rpc} | block {w3.eth.block_number}")
                    return
            except Exception:
                continue
        raise ConnectionError(f"All {self.chain_name} RPCs failed")

    def _rotate_rpc(self):
        """Switch to the next RPC in the list (for 429 rate limits)."""
        current_idx = self.rpcs.index(self.rpc) if self.rpc in self.rpcs else -1
        next_idx = (current_idx + 1) % len(self.rpcs)
        for i in range(len(self.rpcs)):
            rpc = self.rpcs[(next_idx + i) % len(self.rpcs)]
            if rpc == self.rpc:
                continue
            try:
                w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 15}))
                w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
                if w3.is_connected():
                    self.w3 = w3
                    self.rpc = rpc
                    log.info(f"[{self.chain_name}] Rotated RPC to {rpc}")
                    return True
            except Exception:
                continue
        return False

    def _reconnect(self):
        """Reconnect on RPC failure, cycling through providers."""
        self.w3 = None
        self._connect()

    def _add_finding(self, vuln_type, address, details, eth_value=0.0, chain_id=None):
        if chain_id is None:
            chain_id = self.chain_id
        finding = {
            "type": vuln_type,
            "address": address,
            "details": details,
            "eth_value": eth_value,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "chain": self.chain_name.lower(),
            "chain_id": chain_id,
            "action": "Log for review. Submit to Immunefi if bounty-eligible.",
        }

        # Etherscan V2 enrichment — get verified source + deployer intel
        if HAS_ETHERSCAN and eth_value >= 0.01:
            try:
                enrichment = etherscan_enrich(address, chain_id)
                finding["etherscan"] = enrichment

                if enrichment.get("recommendation") == "skip":
                    reason = enrichment.get("skip_reason", "access control detected")
                    log.info(f"[{self.chain_name}] SKIP (Etherscan): {vuln_type} at {address} — {reason}")
                    return None  # Don't add false positive

                if enrichment.get("source_verified"):
                    log.info(f"[{self.chain_name}] ENRICHED: {vuln_type} at {address} — source verified, "
                             f"risk={enrichment.get('source_analysis', {}).get('risk_level', '?')}, "
                             f"rec={enrichment.get('recommendation')}")
            except Exception as e:
                log.debug(f"[{self.chain_name}] Etherscan enrichment failed for {address}: {e}")

        self.findings.append(finding)
        log.info(f"[{self.chain_name}] FINDING: {vuln_type} at {address} ({eth_value:.4f} ETH)")
        self._persist_findings()
        return finding

    def _persist_findings(self):
        try:
            try:
                with open(self.findings_file, "r") as f:
                    existing = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                existing = []
            # Deduplicate by (type, address)
            seen = {(f["type"], f["address"]) for f in existing}
            for f in self.findings:
                key = (f["type"], f["address"])
                if key not in seen:
                    existing.append(f)
                    seen.add(key)
            with open(self.findings_file, "w") as f:
                json.dump(existing, f, indent=2)
        except Exception as e:
            log.error(f"[{self.chain_name}] Failed to persist findings: {e}")

    def _get_code(self, addr):
        try:
            code = self.w3.eth.get_code(Web3.to_checksum_address(addr))
            return code.hex() if code else ""
        except Exception:
            return ""

    def _get_eth_balance(self, addr):
        try:
            bal = self.w3.eth.get_balance(Web3.to_checksum_address(addr))
            return float(self.w3.from_wei(bal, "ether"))
        except Exception:
            return 0.0

    def _get_owner(self, addr):
        """Try common owner() patterns."""
        owner_selector = "0x8da5cb5b"  # owner()
        try:
            result = self.w3.eth.call({
                "to": Web3.to_checksum_address(addr),
                "data": owner_selector,
            })
            if len(result) >= 32:
                return "0x" + result[-20:].hex()
        except Exception:
            pass
        return None

    def _build_calldata(self, selector, addr):
        """Build calldata for a selector, encoding args as needed."""
        sel = selector[2:]  # strip 0x
        if selector in NO_ARG_SELECTORS:
            return "0x" + sel
        if selector in ADDR_ARG_SELECTORS:
            # Encode address arg: pad to 32 bytes (use the caller as dummy recipient)
            return "0x" + sel + SIM_CALLER[2:].lower().zfill(64)
        if selector in UINT_ARG_SELECTORS:
            # Encode uint256 arg: use max uint to simulate withdrawing everything
            return "0x" + sel + "f" * 64
        return "0x" + sel

    def _simulate_call(self, target, calldata, caller=None):
        """Dry-run a call via eth_call. Returns True if it doesn't revert."""
        try:
            self.w3.eth.call({
                "from": Web3.to_checksum_address(caller or SIM_CALLER),
                "to": Web3.to_checksum_address(target),
                "data": calldata,
            })
            return True
        except Exception:
            return False

    def validate_extraction_paths(self, addr, selectors=None):
        """Simulate all dangerous selectors on a contract. Returns dict of callable ones.

        For each selector found in bytecode, tries eth_call from a random
        non-privileged address. If the call doesn't revert, that function
        is genuinely callable by anyone — a real vulnerability.
        """
        addr = Web3.to_checksum_address(addr)
        targets = selectors or DANGEROUS_SELECTORS
        callable_fns = {}

        for selector, name in targets.items():
            calldata = self._build_calldata(selector, addr)
            if self._simulate_call(addr, calldata):
                callable_fns[selector] = name
                log.info(f"CALLABLE: {name} on {addr} (from random caller)")

        return callable_fns

    # ── Check 1: Stuck ETH ──

    def check_stuck_eth(self, addr):
        """Contract has ETH balance + owner renounced to dead address."""
        addr = Web3.to_checksum_address(addr)
        eth_bal = self._get_eth_balance(addr)
        if eth_bal < 0.001:
            return None

        code = self._get_code(addr)
        if not code or code == "0x":
            return None

        owner = self._get_owner(addr)
        if owner and owner.lower() in {d.lower() for d in DEAD_ADDRESSES}:
            return self._add_finding(
                "stuck_eth",
                addr,
                {
                    "eth_balance": eth_bal,
                    "owner": owner,
                    "reason": "Owner renounced to dead address, ETH may be unrecoverable",
                },
                eth_value=eth_bal,
            )

        # Also flag if no owner function at all but has significant ETH
        if owner is None and eth_bal > 0.01:
            return self._add_finding(
                "stuck_eth_no_owner",
                addr,
                {
                    "eth_balance": eth_bal,
                    "reason": "Contract has ETH, no owner() function found",
                },
                eth_value=eth_bal,
            )
        return None

    # ── Check 2: Skimmable Pair ──

    def check_skimmable_pair(self, pair_addr):
        """Uniswap V2 pair where token balance > reserves (excess from accidental sends)."""
        pair_addr = Web3.to_checksum_address(pair_addr)
        try:
            pair = self.w3.eth.contract(address=pair_addr, abi=PAIR_ABI)
            reserves = pair.functions.getReserves().call()
            token0 = pair.functions.token0().call()
            token1 = pair.functions.token1().call()

            reserve0, reserve1 = reserves[0], reserves[1]

            # Get actual balances of tokens held by pair
            t0 = self.w3.eth.contract(address=Web3.to_checksum_address(token0), abi=ERC20_ABI)
            t1 = self.w3.eth.contract(address=Web3.to_checksum_address(token1), abi=ERC20_ABI)

            bal0 = t0.functions.balanceOf(pair_addr).call()
            bal1 = t1.functions.balanceOf(pair_addr).call()

            excess0 = bal0 - reserve0
            excess1 = bal1 - reserve1

            if excess0 <= 0 and excess1 <= 0:
                return None

            # Calculate ETH value of excess if one token is WETH
            eth_value = 0.0
            if token0.lower() == self.weth.lower() and excess0 > 0:
                eth_value = float(Web3.from_wei(excess0, "ether"))
            elif token1.lower() == self.weth.lower() and excess1 > 0:
                eth_value = float(Web3.from_wei(excess1, "ether"))

            # Only report if excess is meaningful
            if excess0 > 1000 or excess1 > 1000 or eth_value > 0.0001:
                return self._add_finding(
                    "skimmable_pair",
                    pair_addr,
                    {
                        "token0": token0,
                        "token1": token1,
                        "reserve0": str(reserve0),
                        "reserve1": str(reserve1),
                        "balance0": str(bal0),
                        "balance1": str(bal1),
                        "excess0": str(excess0),
                        "excess1": str(excess1),
                        "note": "skim() can claim excess tokens sent directly to pair",
                    },
                    eth_value=eth_value,
                )
        except Exception as e:
            log.debug(f"Pair check failed {pair_addr}: {e}")
        return None

    # ── Check 3: Dead Proxy ──

    def check_proxy_dead(self, addr):
        """EIP-1967 proxy pointing to empty/selfdestructed implementation."""
        addr = Web3.to_checksum_address(addr)
        try:
            impl_raw = self.w3.eth.get_storage_at(addr, EIP1967_IMPL_SLOT)
            impl_addr = "0x" + impl_raw[-20:].hex()

            # Check if it's a zero address or if impl has no code
            if impl_addr.lower() in {d.lower() for d in DEAD_ADDRESSES}:
                eth_bal = self._get_eth_balance(addr)
                if eth_bal < 0.01:
                    return None
                return self._add_finding(
                    "proxy_dead_impl",
                    addr,
                    {
                        "implementation": impl_addr,
                        "reason": "Proxy points to zero/dead address",
                        "eth_balance": eth_bal,
                    },
                    eth_value=eth_bal,
                )

            impl_code = self._get_code(impl_addr)
            if not impl_code or impl_code == "0x":
                eth_bal = self._get_eth_balance(addr)
                # Only report if contract actually holds ETH (skip fresh deploys)
                if eth_bal > 0.001:
                    return self._add_finding(
                        "proxy_dead_impl",
                        addr,
                        {
                            "implementation": impl_addr,
                            "reason": "Implementation has no code (selfdestructed?)",
                            "eth_balance": eth_bal,
                        },
                        eth_value=eth_bal,
                    )
        except Exception as e:
            log.debug(f"Proxy check failed {addr}: {e}")
        return None

    # ── Check 4: Unguarded Functions ──

    def check_unguarded_functions(self, addr):
        """Bytecode contains withdraw/sweep/transferOwnership selectors."""
        addr = Web3.to_checksum_address(addr)
        code = self._get_code(addr)
        if not code or code == "0x" or len(code) < 20:
            return None

        found_selectors = {}
        for selector, name in DANGEROUS_SELECTORS.items():
            # Remove 0x prefix for bytecode search
            if selector[2:] in code:
                found_selectors[selector] = name

        if not found_selectors:
            return None

        eth_bal = self._get_eth_balance(addr)

        # Skip contracts with < 0.01 ETH — not worth investigating
        if eth_bal < 0.01:
            return None

        # Skip dead proxies — selectors in proxy bytecode are misleading
        if self.is_dead_proxy(addr):
            log.info(f"Skipping unguarded_functions {addr}: dead proxy (impl is zero/empty)")
            return None

        owner = self._get_owner(addr)

        # Simulate each found selector — only keep ones that don't revert
        callable_fns = self.validate_extraction_paths(addr, found_selectors)
        if not callable_fns:
            log.info(f"Skipping {addr}: selectors found in bytecode but all revert on eth_call")
            return None

        return self._add_finding(
            "unguarded_functions",
            addr,
            {
                "selectors_found": found_selectors,
                "callable_functions": callable_fns,
                "eth_balance": eth_bal,
                "owner": owner,
                "note": f"{len(callable_fns)} function(s) callable by unprivileged caller via eth_call simulation.",
            },
            eth_value=eth_bal,
        )

    # ── Check 5: Scan Recent Contracts ──

    def scan_recent_contracts(self, blocks_back=50):
        """Find new contract deployments, run checks 1/3/4 on each."""
        log.info(f"Scanning last {blocks_back} blocks for new contracts...")
        current_block = self.w3.eth.block_number
        start_block = current_block - blocks_back
        new_contracts = []
        findings = []

        for block_num in range(start_block, current_block + 1):
            try:
                block = self.w3.eth.get_block(block_num, full_transactions=True)
                for tx in block.transactions:
                    # Contract creation: to is None
                    if tx.get("to") is None:
                        receipt = self.w3.eth.get_transaction_receipt(tx["hash"])
                        if receipt and receipt.get("contractAddress"):
                            contract_addr = receipt["contractAddress"]
                            new_contracts.append(contract_addr)
            except Exception as e:
                log.debug(f"Block {block_num} fetch failed: {e}")
                continue

        log.info(f"Found {len(new_contracts)} new contracts in {blocks_back} blocks")

        for addr in new_contracts:
            dead_proxy = False
            try:
                r = self.check_stuck_eth(addr)
                if r:
                    findings.append(r)
            except Exception:
                pass
            try:
                r = self.check_proxy_dead(addr)
                if r:
                    findings.append(r)
                    dead_proxy = True
            except Exception:
                pass
            if not dead_proxy:
                try:
                    r = self.check_unguarded_functions(addr)
                    if r:
                        findings.append(r)
                except Exception:
                    pass
            else:
                log.info(f"Skipping unguarded_functions for {addr}: dead proxy")

        return {
            "blocks_scanned": blocks_back,
            "new_contracts": len(new_contracts),
            "findings": len(findings),
            "contracts": new_contracts[:20],  # cap output
        }

    # ── Check 6: Scan Pairs for Skim ──

    def scan_pairs_for_skim(self, factory_addr, num_pairs=20):
        """Iterate recent pairs from a V2 factory, run skim check."""
        factory_addr = Web3.to_checksum_address(factory_addr)
        log.info(f"Scanning {num_pairs} pairs from factory {factory_addr[:10]}...")
        findings = []
        retries = 0

        try:
            factory = self.w3.eth.contract(address=factory_addr, abi=FACTORY_ABI)
            total_pairs = factory.functions.allPairsLength().call()
            log.info(f"Factory has {total_pairs} pairs total")

            # Scan most recent pairs
            start = max(0, total_pairs - num_pairs)
            for i in range(start, total_pairs):
                try:
                    pair_addr = factory.functions.allPairs(i).call()
                    r = self.check_skimmable_pair(pair_addr)
                    if r:
                        findings.append(r)
                    retries = 0  # Reset on success
                except Exception as e:
                    err_str = str(e)
                    if "429" in err_str or "Too Many Requests" in err_str:
                        retries += 1
                        if retries >= 3:
                            log.info(f"Skim scan: 3 consecutive 429s, stopping early at pair {i}")
                            break
                        log.info(f"Skim scan: 429 at pair {i}, rotating RPC and backing off 10s")
                        self._rotate_rpc()
                        time.sleep(10)
                        # Re-create factory contract with new w3
                        factory = self.w3.eth.contract(address=factory_addr, abi=FACTORY_ABI)
                        continue
                    log.debug(f"Pair {i} failed: {e}")
                    continue
                # Rate limit to avoid RPC throttling
                time.sleep(0.5)
        except Exception as e:
            log.error(f"Factory scan failed: {e}")

        return {
            "factory": factory_addr,
            "pairs_scanned": num_pairs,
            "findings": len(findings),
        }

    # ── Check 7: Uninitialized Proxy ──

    def check_uninitialized_proxy(self, addr):
        """Proxy with callable initialize() that hasn't been called."""
        addr = Web3.to_checksum_address(addr)

        # Check if it's a proxy first
        try:
            impl_raw = self.w3.eth.get_storage_at(addr, EIP1967_IMPL_SLOT)
            impl_addr = "0x" + impl_raw[-20:].hex()
            if impl_addr.lower() in {d.lower() for d in DEAD_ADDRESSES}:
                return None  # Dead proxy, covered by check 3
        except Exception:
            return None

        # Try calling initialize() — if it doesn't revert, it's uninitialized
        initialize_selector = "0x8129fc1c"  # initialize()
        try:
            self.w3.eth.call({
                "to": addr,
                "data": initialize_selector,
            })
            # If we get here, initialize() didn't revert — vulnerable
            eth_bal = self._get_eth_balance(addr)
            return self._add_finding(
                "uninitialized_proxy",
                addr,
                {
                    "implementation": impl_addr,
                    "reason": "initialize() is callable (did not revert)",
                    "eth_balance": eth_bal,
                    "severity": "CRITICAL",
                    "note": "Proxy may be takeover-vulnerable via initialize(). Do NOT call — report via Immunefi.",
                },
                eth_value=eth_bal,
            )
        except Exception:
            # Reverted = already initialized = safe
            pass
        return None

    # ── Check 8: Stuck Trading Fees ──

    def is_dead_proxy(self, addr):
        """Check if address is an EIP-1967 proxy pointing to a dead/empty implementation."""
        try:
            impl_raw = self.w3.eth.get_storage_at(
                Web3.to_checksum_address(addr), EIP1967_IMPL_SLOT
            )
            impl_addr = "0x" + impl_raw[-20:].hex()
            if impl_addr.lower() in {d.lower() for d in DEAD_ADDRESSES}:
                return True
            impl_code = self._get_code(impl_addr)
            if not impl_code or impl_code == "0x":
                return True
        except Exception:
            pass
        return False

    def check_stuck_trading_fees(self, addr):
        """Token contract with ETH + WETH from broken fee mechanism."""
        addr = Web3.to_checksum_address(addr)
        eth_bal = self._get_eth_balance(addr)
        if eth_bal < 0.005:
            return None

        # Skip dead proxies — callable selectors in proxy bytecode are misleading
        if self.is_dead_proxy(addr):
            log.info(f"Skipping stuck_trading_fees {addr}: dead proxy (impl is zero/empty)")
            return None

        # Check if contract holds WETH too
        try:
            weth = self.w3.eth.contract(
                address=Web3.to_checksum_address(self.weth), abi=ERC20_ABI
            )
            weth_bal = weth.functions.balanceOf(addr).call()
            weth_eth = float(Web3.from_wei(weth_bal, "ether"))
        except Exception:
            weth_eth = 0.0

        total = eth_bal + weth_eth
        if total < 0.01:
            return None

        # Check if contract has code (is a token/contract, not EOA)
        code = self._get_code(addr)
        if not code or code == "0x":
            return None

        # Check if owner is dead
        owner = self._get_owner(addr)
        owner_dead = owner and owner.lower() in {d.lower() for d in DEAD_ADDRESSES}

        if owner_dead or total > 0.1:
            # Validate there's actually a callable extraction path
            callable_fns = self.validate_extraction_paths(addr)
            if not callable_fns:
                log.info(f"Skipping stuck_trading_fees {addr}: {total:.4f} ETH but no callable extraction path")
                return None

            return self._add_finding(
                "stuck_trading_fees",
                addr,
                {
                    "eth_balance": eth_bal,
                    "weth_balance": weth_eth,
                    "total_value": total,
                    "owner": owner,
                    "owner_renounced": owner_dead,
                    "callable_functions": callable_fns,
                    "reason": f"Contract holds ETH+WETH with {len(callable_fns)} callable extraction path(s)",
                },
                eth_value=total,
            )
        return None

    # ── Check 9: Immunefi Targets ──

    def check_immunefi_targets(self):
        """List known Immunefi-listed Base protocols for bounty research."""
        # Major Base protocols with Immunefi bounties (manually curated)
        targets = [
            {
                "protocol": "Aerodrome Finance",
                "bounty_url": "https://immunefi.com/bounty/aerodrome/",
                "contracts": [AERODROME_FACTORY],
                "max_bounty": "Up to $200K",
                "notes": "Base-native DEX, V2-style AMM + veToken model",
            },
            {
                "protocol": "Uniswap",
                "bounty_url": "https://immunefi.com/bounty/uniswap/",
                "contracts": [UNISWAP_V2_FACTORY],
                "max_bounty": "Up to $3M",
                "notes": "V2 factory on Base, also V3 deployments",
            },
            {
                "protocol": "Base Bridge",
                "bounty_url": "https://immunefi.com/bounty/base/",
                "contracts": ["0x3154Cf16ccdb4C6d922629664174b904d80F2C35"],
                "max_bounty": "Up to $1M",
                "notes": "L1<>L2 bridge, canonical bridge contracts",
            },
            {
                "protocol": "Moonwell",
                "bounty_url": "https://immunefi.com/bounty/moonwell/",
                "contracts": ["0xfBb21d0380beE3312B33c4353c8936a0F13EF26C"],
                "max_bounty": "Up to $250K",
                "notes": "Lending protocol on Base",
            },
            {
                "protocol": "Seamless Protocol",
                "bounty_url": "https://immunefi.com/bounty/seamlessprotocol/",
                "contracts": [],
                "max_bounty": "Up to $100K",
                "notes": "Lending/borrowing on Base (Aave V3 fork)",
            },
        ]
        log.info(f"Immunefi targets: {len(targets)} Base protocols listed")
        return targets

    # ── Full Scan ──

    def full_scan(self):
        """Orchestrate all scans, return consolidated report."""
        log.info("=" * 60)
        log.info(f"FULL VULNERABILITY SCAN — {self.chain_name} (chain {self.chain_id})")
        log.info("=" * 60)
        start_time = time.time()
        self.findings = []
        report = {
            "scan_time": datetime.now(timezone.utc).isoformat(),
            "rpc": self.rpc,
            "block": self.w3.eth.block_number,
        }

        # 1. Scan recent contracts (last 50 blocks)
        log.info("--- Phase 1: Recent Contract Deployments ---")
        try:
            report["recent_contracts"] = self.scan_recent_contracts(blocks_back=50)
        except Exception as e:
            log.error(f"Recent contract scan failed: {e}")
            report["recent_contracts"] = {"error": str(e)}

        # 2. Scan Uniswap V2 pairs for skim
        log.info("--- Phase 2: Uniswap V2 Skim Scan ---")
        try:
            report["uniswap_v2_skim"] = self.scan_pairs_for_skim(
                UNISWAP_V2_FACTORY, num_pairs=20
            )
        except Exception as e:
            log.error(f"Uniswap V2 skim scan failed: {e}")
            report["uniswap_v2_skim"] = {"error": str(e)}

        # 3. Scan Aerodrome pairs for skim
        log.info("--- Phase 3: Aerodrome Skim Scan ---")
        try:
            report["aerodrome_skim"] = self.scan_pairs_for_skim(
                AERODROME_FACTORY, num_pairs=20
            )
        except Exception as e:
            log.error(f"Aerodrome skim scan failed: {e}")
            report["aerodrome_skim"] = {"error": str(e)}

        # 4. Immunefi targets
        log.info("--- Phase 4: Immunefi Targets ---")
        report["immunefi_targets"] = self.check_immunefi_targets()

        # Summary
        elapsed = time.time() - start_time
        report["total_findings"] = len(self.findings)
        report["findings"] = self.findings
        report["elapsed_seconds"] = round(elapsed, 1)

        log.info(f"Scan complete: {len(self.findings)} findings in {elapsed:.1f}s")
        return report

    # ── Single Address Scan ──

    def scan_address(self, addr, chain_id=8453):
        """Run all applicable checks on a single address, with Etherscan enrichment."""
        addr = Web3.to_checksum_address(addr)
        self.findings = []
        results = []
        dead_proxy = False

        # Run checks in order; skip contradictory checks if dead proxy detected
        for check_fn in [
            self.check_stuck_eth,
            self.check_proxy_dead,
            self.check_unguarded_functions,
            self.check_uninitialized_proxy,
            self.check_stuck_trading_fees,
        ]:
            # Dead proxies make unguarded_functions and stuck_trading_fees unreliable
            if dead_proxy and check_fn.__name__ in (
                "check_unguarded_functions", "check_stuck_trading_fees"
            ):
                log.info(f"Skipping {check_fn.__name__} for {addr}: already flagged as dead proxy")
                continue
            try:
                r = check_fn(addr)
                if r:
                    results.append(r)
                    if r.get("type") == "proxy_dead_impl":
                        dead_proxy = True
            except Exception as e:
                log.debug(f"Check {check_fn.__name__} failed on {addr}: {e}")

        # Etherscan enrichment for the address itself (even if no bytecode findings)
        etherscan_data = None
        if HAS_ETHERSCAN:
            try:
                etherscan_data = etherscan_enrich(addr, chain_id)
            except Exception as e:
                log.debug(f"Etherscan enrichment failed for {addr}: {e}")

        return {
            "address": addr,
            "checks_run": 5,
            "findings": len(results),
            "details": results,
            "etherscan": etherscan_data,
        }


# ── CLI Entry Point ──

if __name__ == "__main__":
    # Add stderr output for CLI usage
    _sh = logging.StreamHandler(sys.stderr)
    _sh.setFormatter(logging.Formatter("[%(asctime)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    log.addHandler(_sh)

    action = sys.argv[1] if len(sys.argv) > 1 else "full"
    scanner = ContractScanner()

    if action == "full":
        result = scanner.full_scan()
    elif action == "recent":
        blocks = int(sys.argv[2]) if len(sys.argv) > 2 else 50
        result = scanner.scan_recent_contracts(blocks_back=blocks)
    elif action == "pairs":
        num = int(sys.argv[2]) if len(sys.argv) > 2 else 20
        result = {
            "uniswap_v2": scanner.scan_pairs_for_skim(UNISWAP_V2_FACTORY, num),
            "aerodrome": scanner.scan_pairs_for_skim(AERODROME_FACTORY, num),
        }
    elif action == "immunefi":
        result = scanner.check_immunefi_targets()
    elif action == "address":
        if len(sys.argv) < 3:
            print(json.dumps({"error": "Usage: contract_scanner.py address 0x..."}))
            sys.exit(1)
        result = scanner.scan_address(sys.argv[2])
    else:
        result = {"error": f"Unknown action: {action}. Use: full, recent, pairs, immunefi, address"}

    print(json.dumps(result, indent=2, default=str))
