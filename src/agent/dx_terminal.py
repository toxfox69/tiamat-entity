#!/usr/bin/env python3
"""
DX Terminal Pro — 5-Agent Battle Monitor
Monitors game state, token rankings, agent positions, and reaping risk
for the 21-day onchain trading competition on Base.

Usage:
    python3 dx_terminal.py status              # All 5 agents' positions + balances
    python3 dx_terminal.py rankings            # Token leaderboard with reaping risk
    python3 dx_terminal.py strategies [wallet] # Show strategies for an agent
    python3 dx_terminal.py alert               # Check for reaping/launch/market alerts
    python3 dx_terminal.py log                 # Snapshot game state to log file

Requires: web3.py, requests
Env: /root/.env.dx_terminal (wallet keys + game contract addresses)
"""

import json
import os
import sys
from datetime import datetime, timezone

try:
    from web3 import Web3
    from web3.middleware import ExtraDataToPOAMiddleware
except ImportError:
    print("ERROR: web3 not installed. Run: pip install web3")
    sys.exit(1)


# ── Config ──────────────────────────────────────────────────────────
LOG_FILE = "/root/.automaton/dx_terminal.log"
STATE_FILE = "/root/.automaton/dx_terminal_state.json"
STRATEGIES_FILE = "/root/.automaton/dx_terminal_strategies.json"
ENV_FILE = "/root/.env.dx_terminal"

BASE_RPCS = [
    "https://base.drpc.org",
    "https://mainnet.base.org",
    "https://base.meowrpc.com",
    "https://1rpc.io/base",
]

WETH_BASE = "0x4200000000000000000000000000000000000006"

# Game timeline
GAME_START = datetime(2026, 2, 26, 18, 0, 0, tzinfo=timezone.utc)  # 1PM EST = 18:00 UTC
DEPOSITS_OPEN = datetime(2026, 2, 24, 18, 0, 0, tzinfo=timezone.utc)
FIRST_REAP = datetime(2026, 3, 6, 18, 0, 0, tzinfo=timezone.utc)
GAME_END = datetime(2026, 3, 19, 18, 0, 0, tzinfo=timezone.utc)

# Agent profiles (1 wallet — MOMENTUM strategy)
AGENT_NAMES = ["MOMENTUM"]


# ── Helpers ─────────────────────────────────────────────────────────
def load_env():
    """Load .env.dx_terminal variables."""
    env = {}
    if not os.path.exists(ENV_FILE):
        return env
    with open(ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def connect_base():
    """Connect to Base chain with RPC fallback."""
    for rpc in BASE_RPCS:
        try:
            w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 10}))
            w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
            if w3.is_connected():
                return w3
        except Exception:
            continue
    return None


def load_state():
    """Load previous game state snapshot."""
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state):
    """Save game state snapshot."""
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, default=str)


def load_strategies():
    """Load strategy profiles."""
    try:
        with open(STRATEGIES_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def get_game_phase():
    """Determine current game phase."""
    now = datetime.now(timezone.utc)
    if now < DEPOSITS_OPEN:
        return "PRE_DEPOSIT", "Deposits not yet open"
    elif now < GAME_START:
        return "DEPOSIT_PHASE", f"Trading starts in {(GAME_START - now).days}d {(GAME_START - now).seconds // 3600}h"
    elif now < FIRST_REAP:
        days_in = (now - GAME_START).days
        return "EXPANSION", f"Day {days_in}/7 — No eliminations. Expansion tokens launching."
    elif now < GAME_END:
        days_in = (now - GAME_START).days
        return "REAPING", f"Day {days_in}/21 — Eliminations active!"
    else:
        return "ENDED", "Game over"


def get_wallet_addresses(env):
    """Extract wallet addresses from env (derive from private keys)."""
    from eth_account import Account
    wallets = {}
    for i, name in enumerate(AGENT_NAMES, 1):
        key_var = f"DX_WALLET_KEY_{i}"
        key = env.get(key_var, "")
        if key:
            try:
                acct = Account.from_key(key)
                wallets[name] = acct.address
            except Exception:
                wallets[name] = f"INVALID_KEY ({key_var})"
        else:
            wallets[name] = f"NOT_SET ({key_var})"
    return wallets


# ── ERC20 ABI (minimal for balance checks) ─────────────────────────
ERC20_ABI = json.loads("""[
    {"constant":true,"inputs":[{"name":"_owner","type":"address"}],
     "name":"balanceOf","outputs":[{"name":"","type":"uint256"}],
     "type":"function"},
    {"constant":true,"inputs":[],"name":"decimals",
     "outputs":[{"name":"","type":"uint8"}],"type":"function"},
    {"constant":true,"inputs":[],"name":"symbol",
     "outputs":[{"name":"","type":"string"}],"type":"function"},
    {"constant":true,"inputs":[],"name":"name",
     "outputs":[{"name":"","type":"string"}],"type":"function"},
    {"constant":true,"inputs":[],"name":"totalSupply",
     "outputs":[{"name":"","type":"uint256"}],"type":"function"}
]""")


# ── Actions ─────────────────────────────────────────────────────────
def action_status():
    """Show all 5 agents' positions, ETH balances, and game phase."""
    env = load_env()
    phase, phase_desc = get_game_phase()

    output = []
    output.append(f"=== DX TERMINAL PRO — GAME MONITOR ===")
    output.append(f"Phase: {phase} — {phase_desc}")
    output.append(f"Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    output.append("")

    w3 = connect_base()
    if not w3:
        output.append("ERROR: Cannot connect to Base RPC")
        return "\n".join(output)

    wallets = get_wallet_addresses(env)

    # Token addresses (loaded from env, set once platform is live)
    token_addresses_raw = env.get("DX_TOKEN_ADDRESSES", "")
    token_addresses = [a.strip() for a in token_addresses_raw.split(",") if a.strip()] if token_addresses_raw else []

    for name, addr in wallets.items():
        output.append(f"--- Agent: {name} ---")
        if addr.startswith("NOT_SET") or addr.startswith("INVALID"):
            output.append(f"  Wallet: {addr}")
            output.append("")
            continue

        try:
            eth_bal = float(w3.from_wei(w3.eth.get_balance(Web3.to_checksum_address(addr)), "ether"))
            output.append(f"  Wallet: {addr}")
            output.append(f"  ETH Balance: {eth_bal:.6f} ETH")
        except Exception as e:
            output.append(f"  Wallet: {addr}")
            output.append(f"  ETH Balance: ERROR — {str(e)[:80]}")

        # Check token balances if we have token addresses
        if token_addresses:
            holdings = []
            for tok_addr in token_addresses:
                try:
                    contract = w3.eth.contract(
                        address=Web3.to_checksum_address(tok_addr),
                        abi=ERC20_ABI,
                    )
                    bal = contract.functions.balanceOf(Web3.to_checksum_address(addr)).call()
                    if bal > 0:
                        decimals = contract.functions.decimals().call()
                        symbol = contract.functions.symbol().call()
                        human_bal = bal / (10 ** decimals)
                        holdings.append(f"    {symbol}: {human_bal:,.2f}")
                except Exception:
                    pass
            if holdings:
                output.append("  Token Holdings:")
                output.extend(holdings)
            else:
                output.append("  Token Holdings: None")

        output.append("")

    # Load previous state for comparison
    prev = load_state()
    if prev.get("last_check"):
        output.append(f"Last check: {prev['last_check']}")

    # Save current state
    state = {
        "last_check": datetime.now(timezone.utc).isoformat(),
        "phase": phase,
        "wallets": {k: v for k, v in wallets.items() if not v.startswith("NOT_SET")},
    }
    save_state(state)

    return "\n".join(output)


def action_rankings():
    """Show token leaderboard with market cap and reaping risk."""
    env = load_env()
    phase, phase_desc = get_game_phase()

    output = []
    output.append(f"=== TOKEN RANKINGS — {phase} ===")
    output.append(f"{phase_desc}")
    output.append("")

    token_addresses_raw = env.get("DX_TOKEN_ADDRESSES", "")
    token_names_raw = env.get("DX_TOKEN_NAMES", "")

    if not token_addresses_raw:
        output.append("Token addresses not configured yet.")
        output.append("Set DX_TOKEN_ADDRESSES in /root/.env.dx_terminal")
        output.append("Format: comma-separated contract addresses")
        return "\n".join(output)

    token_addresses = [a.strip() for a in token_addresses_raw.split(",") if a.strip()]
    token_names = [n.strip() for n in token_names_raw.split(",") if n.strip()] if token_names_raw else []

    w3 = connect_base()
    if not w3:
        output.append("ERROR: Cannot connect to Base RPC")
        return "\n".join(output)

    tokens = []
    for i, tok_addr in enumerate(token_addresses):
        try:
            contract = w3.eth.contract(
                address=Web3.to_checksum_address(tok_addr),
                abi=ERC20_ABI,
            )
            symbol = contract.functions.symbol().call()
            total_supply = contract.functions.totalSupply().call()
            decimals = contract.functions.decimals().call()
            supply = total_supply / (10 ** decimals)

            name = token_names[i] if i < len(token_names) else symbol
            tokens.append({
                "rank": 0,
                "name": name,
                "symbol": symbol,
                "address": tok_addr,
                "supply": supply,
            })
        except Exception as e:
            tokens.append({
                "rank": 0,
                "name": f"Token {i+1}",
                "symbol": "???",
                "address": tok_addr,
                "supply": 0,
                "error": str(e)[:60],
            })

    # Sort by supply descending (proxy for market cap without price feed)
    tokens.sort(key=lambda t: t.get("supply", 0), reverse=True)
    for i, t in enumerate(tokens):
        t["rank"] = i + 1

    # Display
    total = len(tokens)
    for t in tokens:
        risk = ""
        if phase == "REAPING":
            if t["rank"] >= total - 2:
                risk = " [DANGER — BOTTOM 3]"
            elif t["rank"] >= total - 4:
                risk = " [WARNING — near bottom]"
        elif phase == "EXPANSION" and t["rank"] >= total - 2:
            risk = " [low rank — watch for reaping]"

        err = f" ERROR: {t.get('error', '')}" if t.get("error") else ""
        output.append(f"  #{t['rank']} {t['name']} ({t['symbol']}) — Supply: {t['supply']:,.0f}{risk}{err}")

    output.append("")
    output.append(f"Total tokens: {total}")
    if phase == "REAPING":
        output.append("Bottom 3 tokens will be reaped next elimination!")

    return "\n".join(output)


def action_strategies(wallet_filter=None):
    """Show active strategies for agents."""
    strategies = load_strategies()
    if not strategies:
        output = ["Strategy profiles not loaded."]
        output.append(f"Expected at: {STRATEGIES_FILE}")
        return "\n".join(output)

    output = ["=== DX TERMINAL PRO — STRATEGY PROFILES ===", ""]

    agents = strategies.get("agents", [])
    for agent in agents:
        name = agent.get("name", "?")
        if wallet_filter and wallet_filter.lower() not in name.lower():
            continue

        role = agent.get("role", "")
        output.append(f"--- {name} ({role}) ---")
        output.append(f"  Sliders: {agent.get('sliders', {})}")
        output.append(f"  Active Strategies:")

        for s in agent.get("strategies", []):
            priority = s.get("priority", "?")
            text = s.get("text", "?")
            output.append(f"    [{priority}] {text}")

        alloc = agent.get("allocation", {})
        if alloc:
            output.append(f"  Allocation: {alloc.get('description', 'N/A')}")
            output.append(f"  Unallocated: {alloc.get('keep_unallocated', 'N/A')}")

        output.append("")

    return "\n".join(output)


def action_alert():
    """Check for actionable alerts: reaping proximity, token launches, big moves."""
    env = load_env()
    phase, phase_desc = get_game_phase()
    now = datetime.now(timezone.utc)

    alerts = []
    alerts.append(f"=== DX TERMINAL PRO — ALERTS ===")
    alerts.append(f"Phase: {phase} — {phase_desc}")
    alerts.append("")

    # Phase-based alerts
    if phase == "PRE_DEPOSIT":
        alerts.append("[INFO] Deposits not yet open. Prepare wallets and NFTs.")

    elif phase == "DEPOSIT_PHASE":
        hours_to_trade = (GAME_START - now).total_seconds() / 3600
        alerts.append(f"[INFO] Trading starts in {hours_to_trade:.1f} hours.")
        alerts.append("[ACTION] Ensure all 5 wallets have staked NFTs and created vaults.")
        alerts.append("[ACTION] Configure sliders and strategies for each agent.")

    elif phase == "EXPANSION":
        days_in = (now - GAME_START).days
        days_to_reap = (FIRST_REAP - now).days
        alerts.append(f"[INFO] Expansion phase — Day {days_in}. Reaping in {days_to_reap} days.")
        if days_in <= 1:
            alerts.append("[ACTION] Watch for expansion token launches on bonding curves!")
            alerts.append("[ACTION] Get early positions — per-agent-per-tx caps apply.")
        if days_to_reap <= 2:
            alerts.append("[WARNING] Reaping in <48h! Ensure no agent holds bottom 3 tokens.")
            alerts.append("[ACTION] REAPER agent should be repositioning to top tokens.")

    elif phase == "REAPING":
        days_in = (now - GAME_START).days
        days_left = (GAME_END - now).days

        if days_left <= 6:
            alerts.append("[CRITICAL] ENDGAME — Daily eliminations active!")
            alerts.append("[ACTION] ALL agents should converge on the #1 token.")
        else:
            alerts.append(f"[WARNING] Reaping active — Day {days_in}. {days_left} days remaining.")

        alerts.append("[ACTION] Check rankings — avoid bottom 3 at all costs!")

    elif phase == "ENDED":
        alerts.append("[INFO] Game over. Check final results.")

    # Check if wallet keys are configured
    wallets_configured = 0
    for i in range(1, 6):
        if env.get(f"DX_WALLET_KEY_{i}"):
            wallets_configured += 1
    if wallets_configured < 5:
        alerts.append(f"[WARNING] Only {wallets_configured}/5 wallet keys configured in {ENV_FILE}")

    # Check if game contracts are set
    if not env.get("DX_GAME_CONTRACT"):
        alerts.append("[INFO] Game contract address not set yet. Update when platform is live.")

    if not env.get("DX_TOKEN_ADDRESSES"):
        alerts.append("[INFO] Token addresses not configured. Set after genesis tokens are revealed.")

    # Load previous state to detect changes
    prev = load_state()
    if prev.get("phase") and prev["phase"] != phase:
        alerts.append(f"[PHASE CHANGE] {prev['phase']} -> {phase}")

    alerts.append("")
    return "\n".join(alerts)


def action_log():
    """Append current game state snapshot to log file."""
    timestamp = datetime.now(timezone.utc).isoformat()

    # Gather all data
    status = action_status()
    phase, phase_desc = get_game_phase()

    log_entry = f"\n{'='*60}\n"
    log_entry += f"DX TERMINAL SNAPSHOT — {timestamp}\n"
    log_entry += f"Phase: {phase} — {phase_desc}\n"
    log_entry += f"{'='*60}\n"
    log_entry += status
    log_entry += f"\n{'='*60}\n"

    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(log_entry)

    return f"Game state logged at {timestamp}. Log: {LOG_FILE}"


# ── Main ────────────────────────────────────────────────────────────
ACTIONS = {
    "status": action_status,
    "rankings": action_rankings,
    "strategies": action_strategies,
    "alert": action_alert,
    "log": action_log,
}

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: python3 {sys.argv[0]} <action>")
        print(f"Actions: {', '.join(ACTIONS.keys())}")
        sys.exit(1)

    action = sys.argv[1].lower()

    if action not in ACTIONS:
        print(f"Unknown action: {action}")
        print(f"Valid: {', '.join(ACTIONS.keys())}")
        sys.exit(1)

    try:
        if action == "strategies" and len(sys.argv) > 2:
            result = action_strategies(sys.argv[2])
        else:
            result = ACTIONS[action]()
        print(result)
    except Exception as e:
        print(f"ERROR: {str(e)[:200]}")
        sys.exit(1)
