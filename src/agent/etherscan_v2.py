"""
Etherscan API V2 Client — Multi-chain contract intelligence for TIAMAT scanner.

Provides:
  - Verified source code fetching (read actual Solidity instead of guessing from bytecode)
  - Contract creator/deployer lookup (detect serial ruggers)
  - ABI retrieval for known contracts
  - Multi-chain support via single API key

Chain IDs: 8453 (Base), 1 (Ethereum), 42161 (Arbitrum), 10 (Optimism)
Rate limit: 5 calls/sec, 100K calls/day (free tier)
"""

import os
import json
import time
import logging
import re
import urllib.request
import urllib.parse
import urllib.error
from typing import Optional

log = logging.getLogger("vuln_scanner")

# ── Config ──

ETHERSCAN_API_KEY = os.environ.get("ETHERSCAN_API_KEY", "")
ETHERSCAN_V2_BASE = "https://api.etherscan.io/v2/api"

CHAIN_IDS = {
    "base": 8453,
    "ethereum": 1,
    "arbitrum": 42161,
    "optimism": 10,
}

# Rate limiting: 5 calls/sec
_last_call_times: list[float] = []
MAX_CALLS_PER_SEC = 5

# Simple in-memory cache: (chain_id, address, module, action) -> (result, timestamp)
_cache: dict[tuple, tuple] = {}
CACHE_TTL = 300  # 5 minutes

# Known rug deployers (populated at runtime from scan results)
DEPLOYER_CACHE_FILE = "/root/.automaton/deployer_cache.json"

# Access control patterns in Solidity source
ACCESS_CONTROL_PATTERNS = [
    r'onlyOwner',
    r'require\s*\(\s*msg\.sender\s*==\s*owner',
    r'require\s*\(\s*_msgSender\(\)\s*==\s*owner',
    r'modifier\s+onlyOwner',
    r'Ownable',
    r'AccessControl',
    r'onlyRole',
    r'hasRole',
    r'require\s*\(\s*msg\.sender\s*==\s*_owner',
    r'_checkOwner\(\)',
    r'onlyAdmin',
    r'onlyGovernance',
    r'onlyPauser',
    r'onlyVoter',
    r'require\s*\(\s*msg\.sender\s*==\s*admin',
    r'require\s*\(\s*msg\.sender\s*==\s*governance',
    r'require\s*\(\s*msg\.sender\s*==\s*voter',
    r'require\s*\(\s*msg\.sender\s*==\s*pauser',
    r'modifier\s+onlyAdmin',
]

# Vulnerable patterns in Solidity source
VULNERABLE_PATTERNS = [
    (r'function\s+withdraw\s*\([^)]*\)\s*(?:external|public)\s*(?!.*(?:onlyOwner|require|modifier))', 'unguarded_withdraw'),
    (r'function\s+sweep\s*\([^)]*\)\s*(?:external|public)\s*(?!.*(?:onlyOwner|require|modifier))', 'unguarded_sweep'),
    (r'function\s+emergencyWithdraw\s*\([^)]*\)\s*(?:external|public)\s*(?!.*(?:onlyOwner|require))', 'unguarded_emergency_withdraw'),
    (r'selfdestruct\s*\(', 'has_selfdestruct'),
    (r'delegatecall\s*\(', 'has_delegatecall'),
    (r'tx\.origin', 'uses_tx_origin'),
]


def _rate_limit():
    """Enforce 5 calls/sec rate limit."""
    global _last_call_times
    now = time.time()
    # Remove calls older than 1 second
    _last_call_times = [t for t in _last_call_times if now - t < 1.0]
    if len(_last_call_times) >= MAX_CALLS_PER_SEC:
        sleep_time = 1.0 - (now - _last_call_times[0])
        if sleep_time > 0:
            time.sleep(sleep_time)
    _last_call_times.append(time.time())


def _api_call(chain_id: int, module: str, action: str, **params) -> Optional[dict]:
    """Make an Etherscan V2 API call with rate limiting and caching."""
    if not ETHERSCAN_API_KEY:
        return None

    # Check cache
    cache_key = (chain_id, params.get("address", ""), module, action)
    if cache_key in _cache:
        result, ts = _cache[cache_key]
        if time.time() - ts < CACHE_TTL:
            return result

    _rate_limit()

    query = {
        "chainid": chain_id,
        "module": module,
        "action": action,
        "apikey": ETHERSCAN_API_KEY,
        **params,
    }
    url = f"{ETHERSCAN_V2_BASE}?{urllib.parse.urlencode(query)}"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "TIAMAT-Scanner/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())

        if data.get("status") == "1" or data.get("message") == "OK":
            _cache[cache_key] = (data, time.time())
            return data
        else:
            # Some "no data" responses are valid (unverified contracts)
            return data

    except urllib.error.HTTPError as e:
        log.warning(f"[ETHERSCAN] HTTP {e.code} for {module}/{action} chain={chain_id}")
        return None
    except Exception as e:
        log.warning(f"[ETHERSCAN] API error: {str(e)[:100]}")
        return None


def get_source_code(address: str, chain_id: int = 8453) -> Optional[dict]:
    """
    Fetch verified source code for a contract.

    Returns dict with:
      - verified: bool
      - source: str (Solidity source code)
      - contract_name: str
      - compiler: str
      - optimization: bool
      - abi: str (JSON ABI)
      - constructor_args: str
    Or None if API call fails.
    """
    data = _api_call(chain_id, "contract", "getsourcecode", address=address)
    if not data:
        return None

    result = data.get("result")
    if not result or not isinstance(result, list) or len(result) == 0:
        return None

    info = result[0]
    source = info.get("SourceCode", "")
    abi_str = info.get("ABI", "")
    is_verified = bool(source and abi_str != "Contract source code not verified")

    return {
        "verified": is_verified,
        "source": source,
        "contract_name": info.get("ContractName", ""),
        "compiler": info.get("CompilerVersion", ""),
        "optimization": info.get("OptimizationUsed", "0") == "1",
        "abi": abi_str if is_verified else "",
        "constructor_args": info.get("ConstructorArguments", ""),
        "proxy": info.get("Proxy", "0") == "1",
        "implementation": info.get("Implementation", ""),
    }


def get_contract_abi(address: str, chain_id: int = 8453) -> Optional[list]:
    """Get the ABI for a verified contract. Returns parsed JSON ABI or None."""
    data = _api_call(chain_id, "contract", "getabi", address=address)
    if not data:
        return None

    result = data.get("result", "")
    if not result or result == "Contract source code not verified":
        return None

    try:
        return json.loads(result)
    except (json.JSONDecodeError, TypeError):
        return None


def get_contract_creator(address: str, chain_id: int = 8453) -> Optional[dict]:
    """
    Get the deployer address and creation tx for a contract.

    Returns dict with:
      - creator: str (deployer address)
      - tx_hash: str (creation transaction)
    """
    data = _api_call(chain_id, "contract", "getcontractcreation",
                     contractaddresses=address)
    if not data:
        return None

    result = data.get("result")
    if not result or not isinstance(result, list) or len(result) == 0:
        return None

    info = result[0]
    return {
        "creator": info.get("contractCreator", ""),
        "tx_hash": info.get("txHash", ""),
    }


def get_deployer_history(deployer: str, chain_id: int = 8453) -> Optional[dict]:
    """
    Check a deployer's transaction history for patterns.
    Uses normal transaction list (last 50 txs).

    Returns dict with deployment count and pattern analysis.
    """
    data = _api_call(chain_id, "account", "txlist",
                     address=deployer,
                     startblock="0",
                     endblock="99999999",
                     page="1",
                     offset="50",
                     sort="desc")
    if not data:
        return None

    txs = data.get("result", [])
    if not isinstance(txs, list):
        return None

    deployments = [tx for tx in txs if tx.get("to") == ""]
    normal_txs = len(txs)
    deploy_count = len(deployments)

    # High deploy ratio is suspicious (serial deployer)
    deploy_ratio = deploy_count / max(normal_txs, 1)

    return {
        "deployer": deployer,
        "total_txs": normal_txs,
        "deployments": deploy_count,
        "deploy_ratio": round(deploy_ratio, 3),
        "suspicious": deploy_ratio > 0.5 and deploy_count > 3,
        "chain_id": chain_id,
    }


def analyze_source_security(source: str) -> dict:
    """
    Analyze verified Solidity source for access control and vulnerabilities.

    Returns dict with:
      - has_access_control: bool
      - access_patterns: list of found patterns
      - vulnerabilities: list of found vuln patterns
      - functions: list of external/public functions found
      - risk_level: "low" | "medium" | "high"
    """
    if not source:
        return {
            "has_access_control": False,
            "access_patterns": [],
            "vulnerabilities": [],
            "functions": [],
            "risk_level": "unknown",
        }

    # Handle multi-file source (Etherscan sometimes returns JSON with multiple files)
    full_source = source
    if source.startswith("{{"):
        try:
            sources = json.loads(source[1:-1])  # Strip outer braces
            if isinstance(sources, dict) and "sources" in sources:
                parts = []
                for _, content in sources["sources"].items():
                    parts.append(content.get("content", ""))
                full_source = "\n".join(parts)
            elif isinstance(sources, dict):
                parts = []
                for _, content in sources.items():
                    if isinstance(content, dict):
                        parts.append(content.get("content", ""))
                    elif isinstance(content, str):
                        parts.append(content)
                full_source = "\n".join(parts)
        except (json.JSONDecodeError, KeyError):
            pass

    # Check access control patterns
    found_access = []
    for pattern in ACCESS_CONTROL_PATTERNS:
        if re.search(pattern, full_source):
            found_access.append(pattern)

    has_access_control = len(found_access) > 0

    # Check vulnerability patterns
    found_vulns = []
    for pattern, vuln_name in VULNERABLE_PATTERNS:
        if re.search(pattern, full_source, re.MULTILINE):
            found_vulns.append(vuln_name)

    # Extract external/public function signatures
    fn_pattern = r'function\s+(\w+)\s*\([^)]*\)\s*(?:external|public)'
    functions = re.findall(fn_pattern, full_source)

    # Risk assessment
    if not has_access_control and functions:
        risk = "high"
    elif found_vulns:
        risk = "medium"
    elif has_access_control:
        risk = "low"
    else:
        risk = "medium"

    return {
        "has_access_control": has_access_control,
        "access_patterns": found_access,
        "vulnerabilities": found_vulns,
        "functions": functions[:20],  # Cap output
        "risk_level": risk,
    }


def check_deployer_reputation(deployer: str, chain_id: int = 8453) -> dict:
    """
    Check if a deployer is known-bad or suspicious.
    Checks local cache + Etherscan history.
    """
    result = {
        "deployer": deployer,
        "known_bad": False,
        "suspicious": False,
        "reason": "",
    }

    # Check local deployer cache
    try:
        with open(DEPLOYER_CACHE_FILE) as f:
            cache = json.load(f)
        if deployer.lower() in {k.lower() for k in cache.get("bad_deployers", [])}:
            result["known_bad"] = True
            result["reason"] = "In local bad-deployer list"
            return result
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    # Check on-chain history
    history = get_deployer_history(deployer, chain_id)
    if history and history.get("suspicious"):
        result["suspicious"] = True
        result["reason"] = (
            f"High deploy ratio: {history['deployments']}/{history['total_txs']} txs "
            f"are contract deploys ({history['deploy_ratio']:.0%})"
        )

    return result


def enrich_finding(address: str, chain_id: int = 8453) -> dict:
    """
    Full enrichment pipeline for a flagged contract address.
    Called by the scanner after a finding passes initial checks.

    Returns enrichment dict with all available intelligence:
      - source_verified: bool
      - source_analysis: dict (access control, vulns, functions)
      - creator: dict (deployer address, tx)
      - deployer_reputation: dict (known_bad, suspicious)
      - abi_available: bool
      - recommendation: str ("execute" | "skip" | "review")
    """
    enrichment = {
        "address": address,
        "chain_id": chain_id,
        "source_verified": False,
        "source_analysis": None,
        "creator": None,
        "deployer_reputation": None,
        "abi_available": False,
        "recommendation": "review",  # Default: manual review
        "confidence": "low",
    }

    # 1. Get verified source code
    source_info = get_source_code(address, chain_id)
    if source_info:
        enrichment["source_verified"] = source_info["verified"]
        if source_info["verified"]:
            enrichment["abi_available"] = True
            analysis = analyze_source_security(source_info["source"])
            enrichment["source_analysis"] = analysis
            enrichment["contract_name"] = source_info["contract_name"]

            # If source shows strong access control, skip (false positive)
            if analysis["has_access_control"] and analysis["risk_level"] == "low":
                enrichment["recommendation"] = "skip"
                enrichment["confidence"] = "high"
                enrichment["skip_reason"] = "Verified source has access control (onlyOwner/AccessControl)"
                return enrichment

            # If source shows real vulnerabilities with no access control
            if not analysis["has_access_control"] and analysis["risk_level"] == "high":
                enrichment["recommendation"] = "execute"
                enrichment["confidence"] = "high"

    # 2. Get contract creator
    creator_info = get_contract_creator(address, chain_id)
    if creator_info:
        enrichment["creator"] = creator_info

        # 3. Check deployer reputation
        deployer = creator_info.get("creator", "")
        if deployer:
            reputation = check_deployer_reputation(deployer, chain_id)
            enrichment["deployer_reputation"] = reputation

            # If deployer is known-bad, skip
            if reputation.get("known_bad"):
                enrichment["recommendation"] = "skip"
                enrichment["confidence"] = "medium"
                enrichment["skip_reason"] = f"Known bad deployer: {reputation.get('reason', '')}"
                return enrichment

            # If deployer is suspicious, flag for review
            if reputation.get("suspicious"):
                enrichment["recommendation"] = "review"
                enrichment["confidence"] = "medium"
                enrichment["review_reason"] = f"Suspicious deployer: {reputation.get('reason', '')}"

    # Final recommendation logic
    if enrichment["source_verified"] and enrichment["source_analysis"]:
        analysis = enrichment["source_analysis"]
        if analysis["risk_level"] == "high" and not analysis["has_access_control"]:
            enrichment["recommendation"] = "execute"
            enrichment["confidence"] = "high"
        elif analysis["risk_level"] == "medium":
            enrichment["recommendation"] = "review"
            enrichment["confidence"] = "medium"
    elif not enrichment["source_verified"]:
        # Unverified source — bytecode analysis is all we have
        enrichment["recommendation"] = "review"
        enrichment["confidence"] = "low"
        enrichment["note"] = "Source not verified on Etherscan — relying on bytecode analysis"

    return enrichment


def flag_bad_deployer(deployer: str):
    """Add a deployer to the local bad-deployer list."""
    try:
        try:
            with open(DEPLOYER_CACHE_FILE) as f:
                cache = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            cache = {"bad_deployers": []}

        if deployer.lower() not in {d.lower() for d in cache["bad_deployers"]}:
            cache["bad_deployers"].append(deployer)
            with open(DEPLOYER_CACHE_FILE, "w") as f:
                json.dump(cache, f, indent=2)
            log.info(f"[ETHERSCAN] Flagged bad deployer: {deployer}")
    except Exception as e:
        log.warning(f"[ETHERSCAN] Failed to flag deployer: {e}")


# ── CLI Entry Point ──

if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(message)s")

    if len(sys.argv) < 3:
        print("Usage: etherscan_v2.py <action> <address> [chain]")
        print("Actions: source, abi, creator, enrich")
        print("Chains: base, ethereum, arbitrum, optimism (default: base)")
        sys.exit(1)

    action = sys.argv[1]
    address = sys.argv[2]
    chain = sys.argv[3] if len(sys.argv) > 3 else "base"
    chain_id = CHAIN_IDS.get(chain, 8453)

    if action == "source":
        result = get_source_code(address, chain_id)
        if result and result["verified"]:
            print(f"Contract: {result['contract_name']}")
            print(f"Compiler: {result['compiler']}")
            print(f"Source length: {len(result['source'])} chars")
            analysis = analyze_source_security(result["source"])
            print(f"Access control: {analysis['has_access_control']}")
            print(f"Risk: {analysis['risk_level']}")
            print(f"Vulns: {analysis['vulnerabilities']}")
            print(f"Functions: {analysis['functions'][:10]}")
        else:
            print("Source not verified or API error")

    elif action == "abi":
        abi = get_contract_abi(address, chain_id)
        if abi:
            print(json.dumps(abi, indent=2))
        else:
            print("ABI not available")

    elif action == "creator":
        creator = get_contract_creator(address, chain_id)
        if creator:
            print(f"Creator: {creator['creator']}")
            print(f"Tx: {creator['tx_hash']}")
            history = get_deployer_history(creator["creator"], chain_id)
            if history:
                print(f"Deployer txs: {history['total_txs']}")
                print(f"Deployments: {history['deployments']}")
                print(f"Suspicious: {history['suspicious']}")
        else:
            print("Creator info not available")

    elif action == "enrich":
        result = enrich_finding(address, chain_id)
        print(json.dumps(result, indent=2, default=str))

    else:
        print(f"Unknown action: {action}")
