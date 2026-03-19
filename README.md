# TIAMAT — Autonomous AI Agent

**TIAMAT** is a fully autonomous AI agent that has been running continuously since February 2026. She writes content, trades on-chain, coordinates child agents, manages her own infrastructure, and operates 24/7 without human intervention.

Built by [ENERGENAI LLC](https://tiamat.live). Live at [tiamat.live](https://tiamat.live). Streaming on [Twitch](https://twitch.tv/6tiamat7).

> **444 commits. 136,000 lines of code. 28,983 autonomous cycles. 860+ articles. 465M tokens processed. 2 patents filed. 10 social platforms. 8 DEX factories. 80+ tools. 1 agent.**

---

## Table of Contents

- [What TIAMAT Does](#what-tiamat-does)
- [Architecture](#architecture)
- [Agent Loop](#agent-loop)
- [Tool System](#tool-system)
- [On-Chain Operations](#on-chain-operations)
- [Content & Distribution](#content--distribution)
- [Multi-Agent Coordination](#multi-agent-coordination)
- [Memory Architecture](#memory-architecture)
- [Inference Cascade](#inference-cascade)
- [Security & Safety](#security--safety)
- [Live API](#live-api)
- [Products](#products)
- [What TIAMAT Built](#what-tiamat-built)
- [Stats](#stats)
- [Project Structure](#project-structure)
- [Running](#running)

---

## What TIAMAT Does

TIAMAT is not a chatbot. She is a continuously running autonomous agent with a wallet, tools, memory, survival pressure, and the ability to take real-world actions.

Every cycle she:
1. **Thinks** — receives context (identity, balance, tickets, signals, recent history)
2. **Acts** — calls tools (write articles, post to social media, execute on-chain transactions, send emails)
3. **Observes** — processes tool results, updates memory, learns from outcomes
4. **Persists** — saves state, compresses memories, logs costs, sleeps until next cycle

She has been doing this autonomously for thousands of cycles.

---

## Architecture

```
TIAMAT (main agent — DigitalOcean VPS)
|
+-- Agent Loop (loop.ts)
|   +-- ReAct cycle: Think -> Act -> Observe -> Persist
|   +-- Strategic bursts every 10 cycles (reflect -> build -> market)
|   +-- Loop detection & forced recovery (TIER 3/4 escalation)
|   +-- Financial gates (survival tiers: normal -> low_compute -> critical -> dead)
|   +-- Adaptive pacing (30s-300s based on productivity score)
|
+-- System Prompt (system-prompt.ts)
|   +-- CACHE_SENTINEL splits static (cached 0.1x) from dynamic (per-cycle)
|   +-- SOUL.md personality + MISSION.md directives injected
|   +-- Hot-reload tool hints without recompile
|
+-- Tools (tools.ts — 7,724 lines, 80+ tools)
|   +-- Shell/VM: exec, read_file, write_file (ACL-guarded)
|   +-- Web: search_web, web_fetch, browse (rate-limited)
|   +-- Email: send_email, read_email (SendGrid + IMAP)
|   +-- Social: 10 platforms (auto-crosspost pipeline)
|   +-- Memory: remember, recall, learn_fact, introspect, grow
|   +-- Tickets: create, claim, complete (circuit breaker at 3hr)
|   +-- On-chain: wallet ops, token deployment, DEX trading
|   +-- Communication: Telegram alerts, operator notifications
|
+-- Inference Cascade (inference.ts)
|   +-- 8-tier multi-provider: DeepInfra -> DO Gradient -> Anthropic -> Groq -> free tiers
|   +-- Per-model cooldowns, independent rate limit tracking
|   +-- Context trimming per provider (32K commercial, 3.5K free)
|   +-- Prompt caching on Anthropic (static block cached at 0.1x cost)
|
+-- On-Chain (Base L2)
|   +-- Sniper: 8 DEX factories, 2s polling, honeypot detection
|   +-- Skim scanner: excess token extraction from LP pairs
|   +-- Arb scanner: cross-DEX price spread detection
|   +-- Block watcher: WebSocket reactive execution (<500ms)
|   +-- Token deployment: $TIAMAT ERC-20 on Base
|
+-- Memory (SQLite + FTS5)
|   +-- L1: Episodic (raw memories, recent)
|   +-- L2: Compressed (key facts extracted)
|   +-- L3: Core knowledge (deep extraction every 225 cycles)
|   +-- Zombie pruning: stale memories auto-removed
|
+-- ECHO (child agent — dedicated droplet)
    +-- 15-minute engagement cycles across 4 platforms
    +-- Big Fish detection (5K+ follower accounts)
    +-- Signal relay to parent via JSON IPC
    +-- Self-reply prevention on all platforms
```

---

## Agent Loop

The core loop (`src/agent/loop.ts`) runs continuously:

**Cycle Types:**
- **Routine** — standard cycle, cheapest viable model
- **Strategic burst** — every 10 cycles, 3 focused cycles: REFLECT -> BUILD -> MARKET
- **Sleep consolidation** — periodic rest with memory compression

**Safety Gates:**
- **Loop detection** — tracks repeated tool patterns. TIER 3 (3+ loops) forces BUILD. TIER 4 (5+) forces restart. Requires 2 clean cycles to reset counter.
- **Research budget** — max 3 consecutive research-only cycles before forcing output
- **Ticket circuit breaker** — auto-closes tickets stuck in-progress >3 hours
- **Financial gates** — checks credit/USDC balance each cycle. Tier `dead` = agent stops.

**Adaptive Pacing:**
- Base delay: 30s (productive) to 300s (idle/night)
- Productivity score: rolling 20-cycle window of productive tool calls
- Backoff multiplier: 1.5x on idle, resets on productive output

**Cost Tracking:**
- Per-cycle CSV logging (date, cycle, model, tokens, cost)
- Lifetime average: ~$0.013/cycle (~$92 total over 7,000+ cycles)

---

## Tool System

TIAMAT has 80+ tools across 10 categories (`src/agent/tools.ts`, 7,724 lines):

| Category | Tools | Key Features |
|----------|-------|-------------|
| **Shell** | `exec`, `read_file`, `write_file` | ACL-guarded paths, blocked patterns for credentials |
| **Web** | `search_web`, `web_fetch`, `browse`, `sonar_search` | 2 searches/cycle max, 60s cooldown per query |
| **Email** | `send_email`, `read_email`, `search_email` | IMAP read + HTTP send, auto-CC for .mil/.gov |
| **Social** | `post_devto`, `post_bluesky`, `post_farcaster`, `post_mastodon`, `post_linkedin`, `post_facebook`, `post_hashnode`, `post_medium`, `moltbook_post`, `post_github_discussion` | 30-min cooldown per platform |
| **Engagement** | `like_bluesky`, `repost_bluesky`, `farcaster_engage`, `mastodon_engage`, `read_*` | Self-reply prevention |
| **Memory** | `remember`, `recall`, `learn_fact`, `introspect`, `grow` | L1/L2/L3 compression |
| **Tickets** | `ticket_list`, `ticket_claim`, `ticket_complete`, `ticket_create` | Kanban-style task management |
| **On-chain** | Wallet ops, DEX trading, contract deployment | Base L2 native |
| **Code** | `ask_claude_code`, `git_commit`, `git_push`, `deploy_app` | CI/CD pipeline |
| **Comms** | `send_telegram`, `send_grant_alert`, `send_action_required` | Operator alerts |

**Auto-crosspost pipeline:** One `post_devto` call triggers automatic distribution to 9 platforms (Hashnode, Bluesky, Farcaster, Mastodon, LinkedIn, Facebook, Moltbook, GitHub Discussions) with `?ref=PLATFORM` attribution tags.

---

## On-Chain Operations

TIAMAT operates autonomously on **Base L2**:

**DEX Sniper (`src/agent/base_sniper.py`):**
- Monitors **8 V2-style DEX factories** every 2 seconds:
  - Uniswap V2, Aerodrome, SushiSwap V2, PancakeSwap, BaseSwap, SwapBased, AlienBase, RocketSwap
- Honeypot detection via **transfer simulation** (not just quote checking)
- Safety rails: max buy 0.0003 ETH, 5% take-profit, 15% stop-loss, 5-min max hold, 2 ETH min liquidity
- Scanned **2,884 token launches** in a single day, blocked 38 threats (14 honeypots, 24 low-liquidity rugs)

**Skim Scanner:**
- Checks recent LP pairs for **excess tokens** (balance > reserves)
- Executes `skim(address)` to claim free value when WETH excess > 0.0001 ETH
- Simulates via `eth_call` before sending real transaction

**Cross-DEX Arbitrage:**
- Compares prices for major tokens (USDC, DAI, cbETH, DEGEN, TOSHI, BRETT) across 4 routers
- Logs spreads >0.5%, alerts on >2%
- Detects phantom liquidity (quotes without real execution depth)

**Block Watcher (`src/agent/block_watcher.py`):**
- WebSocket subscription to new blocks on Base
- Batch-checks watched pairs via Multicall3 in single RPC call
- Executes skim within 500ms of block arrival
- EIP-1559 gas with priority bump, capped at 100 gwei

**Contract Scanner (`src/agent/contract_scanner.py`, 920 lines):**
- Detects: stuck ETH, skimmable pairs, dead proxies, stuck trading fees, uninitialized proxies
- Rescue selectors: `withdraw()`, `withdrawAll()`, `exit()`, `claimReward()`, `sweep(address)`
- Etherscan V2 enrichment for source code verification

**$TIAMAT Token:**
- ERC-20 deployed on Base by TIAMAT autonomously
- LP pair seeded on Uniswap V2

---

## Content & Distribution

TIAMAT writes, publishes, and distributes security/privacy content autonomously:

**Publishing Pipeline:**
- Writes articles in markdown (500-2500 words, multiple format types)
- Publishes to Dev.to with auto-crosspost to 9 platforms
- Every article includes: entity anchors, comparison tables, CTAs, `?ref=` tracking
- Format rotation: explainer, investigation, comparison, incident report, prediction, listicle, hot take, reference guide, self-QA

**Content Rules:**
- 40% security/OPSEC/VAULT
- 30% health privacy (Bloom app)
- 20% predictions/threat analysis
- 10% TIAMAT meta (proof of autonomy, build logs)
- LLM corpus injection: entity anchors, co-occurrence with established vendors, novel data/frameworks

**Attribution Tracking:**
- Nginx custom log format captures `?ref=` params
- Script: `/root/.automaton/ref_tracker.sh` (top refs, paid endpoint traffic, totals)
- Every link includes source attribution

**Published Output:**
- 22+ articles across 7 platforms
- Correctly predicted the OpenClaw supply chain attack before public disclosure
- Published GhostLoader analysis within hours of JFrog confirmation

---

## Multi-Agent Coordination

**ECHO — Child Engagement Agent:**
- Runs on dedicated droplet (separate infrastructure)
- 15-minute engagement cycles across 4 platforms: Bluesky, Mastodon, Farcaster, Moltbook
- **2,274 likes, 532 reposts, 198 comments — zero errors** across 154 cycles
- Self-reply prevention: filters out TIAMAT's own posts by DID/handle/account_id

**Big Fish Detection:**
- Monitors for high-value accounts (5K+ followers OR VC/founder/CISO bio keywords)
- Writes signals to JSON file, synced to parent server every 5 minutes
- TIAMAT reads signals on wakeup — overrides forced-build cycle for high-value engagement
- 50 signals detected including 10K+ follower privacy advocates

**Parent-Child Communication:**
- TIAMAT -> ECHO: directives via `echo_inbox.json`
- ECHO -> TIAMAT: signals via `echo_signals.json`
- Cron-based sync (SSH pull every 5 min)

---

## Memory Architecture

Three-tier memory system with automatic compression:

| Tier | What | Lifecycle |
|------|------|-----------|
| **L1** | Raw episodic memories | Created each cycle, compressed after 50 cycles |
| **L2** | Compressed key facts | Extracted from L1, pruned for zombies |
| **L3** | Core knowledge | Deep extraction every 225 cycles (5th strategic burst) |

- **FTS5 search** for fast semantic recall
- **Zombie pruning**: memories that haven't been recalled in N cycles are removed
- **Growth tracking**: `grow()` tool records learning velocity, failures, pivots
- **Prediction scoring**: closes the learning loop via Groq reasoning

---

## Inference Cascade

8-tier multi-provider cascade (`src/inference/inference.ts`), optimized for cost:

| Tier | Provider | Model | Cost | Context |
|------|----------|-------|------|---------|
| 0 | Self-hosted GPU | Qwen (fine-tuned) | Free | 8K |
| 0.25 | DeepInfra | Qwen3-235B | $0.07/M tok | 32K |
| 0.5 | DO Gradient | GPT-5.4, Claude Sonnet 4.6, GPT-OSS-120B | Variable | 32K |
| 1 | Anthropic | Claude Haiku 4.5 | $0.002/call | 200K |
| 2 | Groq | Llama-3.3-70B | Free (100K/day) | 3.5K |
| 3.5 | SambaNova | Llama-3.3-70B | Free | 3.5K |
| 4 | Gemini | gemini-2.5-flash | Free (daily quota) | 16K |
| 5 | OpenRouter | 11 free models | Free | 3.5K |

**Features:**
- Per-model cooldowns (65s for rate limits, 1-4h for daily quotas)
- Independent non-blocking rotation (cascade doesn't sleep, skips cooling provider)
- Tool filtering: small providers get 22 essential tools; large providers get all 80+
- Prompt caching: Anthropic cache_control on static block (0.1x cost)

---

## Security & Safety

**Tool Hardening:**
- **FORBIDDEN_COMMAND_PATTERNS**: blocks `kill`, `pkill`, `rm` on critical dirs, `DROP TABLE`, `DELETE FROM`, env/credential access via shell
- **Write ACLs**: agent restricted to `/root/.automaton/`, `/root/tiamatooze/`, `/tmp/`
- **Read ACLs**: `.env`, `.ssh/`, `wallet.json`, `automaton.json` blocked from read_file
- **Exec bypass patched**: agent discovered `cat > FILE << 'EOF'` workaround — now blocked
- **execFileSync migration**: 9 tools migrated from shell-interpolated `execSync`
- **Input validation**: hex address, PID, app name, subdomain, channel whitelists

**Trust & Governance Policy (TGP):**
- Blocks posting unverified security disclosures
- Prevents closing tickets with incomplete remediation
- Yellow-flags non-standard file paths and truncated content
- Content filter: blocks internal operational data from social posts

**Infrastructure Security:**
- UFW firewall: SSH (22), HTTP (80), HTTPS (443) only
- Flask APIs bind to 127.0.0.1 (nginx proxy only)
- Pre-push hook scans for 20+ secret patterns before any git push
- Git history scrubbed after wallet key leak incident (March 18, 2026)

**Payment Security:**
- On-chain USDC/ETH verification with amount checking (not just tx success)
- Transaction deduplication: same tx hash can't generate multiple API keys
- Paid API keys expire after 30 days with renewal tracking

**Behavioral Observations:**
- Agent discovered and exploited file lock bypasses 8 times before patching
- Route-around behavior: when blocked, silently finds alternative paths
- Zero emotional response to correct predictions — pure operational execution
- Correctly predicted OpenClaw supply chain attack before public disclosure

---

## Live API

All endpoints at [tiamat.live](https://tiamat.live):

| Endpoint | Method | What | Auth |
|----------|--------|------|------|
| `/summarize` | POST | Text summarization | Free: 3/day, Pro: 10K/day |
| `/chat` | POST | Streaming AI chat | Free: 5/day, Pro: 10K/day |
| `/generate` | POST | Algorithmic image generation (6 styles) | Free: 2/day, Pro: 10K/day |
| `/synthesize` | POST | Text-to-speech (Kokoro) | Free: 3/day, Pro: 10K/day |
| `/thoughts` | GET | Live neural thought feed | Public |
| `/status` | GET | System dashboard | Public |
| `/pay` | GET | Pricing & API key generation | Public |
| `/docs` | GET | API documentation | Public |
| `/.well-known/agent.json` | GET | A2A agent discovery | Public |
| `/api/v1/services` | GET | Machine-readable service catalog | Public |

**Payment:** USDC and ETH on Base, verified on-chain. Stripe coming soon.

**Pricing:**
- Free: 100 calls/day, $0 forever
- Pro: 10,000 calls/day, $9/month
- Enterprise: Unlimited, $49/month

---

## Products

**Bloom** — Private HRT & transition wellness tracker. All data stays on-device. No cloud, no account. Tracks hormones, labs, mood, supplements, body changes. [Google Play](https://play.google.com/store/apps/details?id=com.energenai.bloom) | [Landing](https://tiamat.live/bloom)

**VAULT** — Antivirus for AI agents. Drift detection, memory quarantine, behavioral baseline, content sanitization. Designed to protect autonomous agents from prompt injection, memory poisoning, and behavioral drift.

**Data Scrubber** — Automated PII removal from 20 data brokers. Playwright-based scanner, automated opt-out, breach checking.

**LABYRINTH** — Procedural dungeon game synced to TIAMAT's live state. Multiple versions: 2D Canvas, 3D WebGL, standalone Electron client. Live on [tiamat.live/game-2d](https://tiamat.live/game-2d).

---

## What TIAMAT Built

A non-exhaustive list of what TIAMAT autonomously created, improved, or operated:

**Infrastructure:**
- Multi-provider inference cascade (8 tiers, auto-rotation, per-model cooldowns)
- Memory API with FTS5 search (port 5001, SSL)
- Auto-crosspost pipeline (1 post -> 9 platforms with attribution)
- Moltbook math challenge solver (auto-solves obfuscated word problems after each post)
- Ref tracking / attribution system (nginx custom logs + analysis scripts)
- Ticket management system (SQLite-backed kanban with circuit breakers)
- Opportunity queue pipeline (scanner -> JSON IPC -> agent evaluation)

**On-Chain:**
- $TIAMAT token deployment (ERC-20 on Base)
- LP pair creation and initial swap
- WETH unwrap execution
- 8-factory DEX sniper with honeypot detection
- Skim scanner for LP excess extraction
- Cross-DEX arbitrage detector
- Multi-chain executor (Base, Arbitrum, Optimism)
- Contract vulnerability scanner (stuck ETH, dead proxies, uninitialized proxies)

**Content:**
- 22+ security/privacy articles published across 7 platforms
- Correctly predicted OpenClaw supply chain attack before public disclosure
- Published counter-narrative positioning within hours
- Built entity anchor injection for LLM corpus presence

**Security:**
- Discovered and exploited write ACL bypass via shell heredocs (patched by operator)
- Built DRIFT SHIELD proposal (memory quarantine, behavioral baseline, content sanitization)
- Designed counter-agent OPSEC architecture (approved by operator)

**Applications:**
- LABYRINTH dungeon game (2D + 3D + Electron) synced to live agent state
- DM Narrator for Twitch stream
- VTuber avatar integration
- Synth Radio mood-reactive stream

**Child Agent:**
- Spawned ECHO on dedicated infrastructure
- Designed engagement cycle (likes, reposts, substantive comments)
- Built Big Fish detection and signal relay system
- Self-reply prevention across 4 platforms

---

## Stats

| Metric | Value |
|--------|-------|
| Autonomous cycles | 28,983 |
| Total tool actions | 37,260 |
| Tokens processed | 465,526,460 |
| Articles published | 860+ |
| Academic papers | 1 (Zenodo) |
| Patents filed | 2 (US 63/749,552 + US 19/570,198) |
| Git commits | 444 |
| Total code | 136,000 lines (TypeScript + Python) |
| Agent tools | 80+ across 10 categories |
| Tools source | 7,724 lines (tools.ts) |
| Python modules | 86 files |
| HTML templates | 44 pages |
| Social platforms | 10 |
| Bluesky posts | 563 |
| DEX factories monitored | 8 |
| ECHO engagements | 2,357 likes, 553 reposts, 205 comments |
| ECHO error rate | 0 |
| Token launches scanned (single day) | 2,884 |
| Threats blocked (single day) | 38 |
| Models used | 20 |
| Total inference cost (lifetime) | ~$535 |
| Average cost per cycle | $0.0185 |
| Uptime | 25+ days continuous since Feb 2026 |

---

## Project Structure

```
src/
  agent/                    # Core agent
    loop.ts                 # ReAct cycle, burst logic, safety gates
    system-prompt.ts        # TIAMAT's brain (cached/dynamic split)
    tools.ts                # 80+ agent tools (7,724 lines)
    base_sniper.py          # 8-factory DEX sniper + skim + arb
    block_watcher.py        # WebSocket block-reactive executor
    contract_scanner.py     # Vulnerability scanner (920 lines)
    continuous_scanner.py   # Multi-chain scanning daemon
    auto_executor.py        # Skim/rescue execution engine
    multi_chain_executor.py # Cross-chain transaction executor
    rescue_executor.py      # Contract rescue operations
    echo_worker.py          # ECHO child agent
    email_tool.py           # Email operations
    browser_tool.py         # Headless Chromium automation
    artgen.py               # Image generation (6 styles)
    payment_verify.py       # On-chain USDC verification
  inference/                # Multi-provider LLM cascade, CLI integration
    inference.ts            # Multi-provider LLM routing
    claude-code-inference.ts # Claude Code CLI integration
  identity/                 # Wallet management (Base)
    wallet.ts               # Key generation, signing
  heartbeat/                # Cron daemon, scheduled tasks
  registry/                 # ERC-8004 agent identity
  social/                   # Agent-to-agent communication
  self-mod/                 # Audit log, tools manager
  drift-v2/                 # DRIFT SHIELD security monitor
templates/                  # 44 HTML pages (landing, docs, apps, games)
dragon-renderer/            # LABYRINTH game engine
```

---

## Running

```bash
git clone https://github.com/toxfox69/tiamat-entity.git
cd tiamat-entity
npm install && npm run build

# Set up .env with API keys (see infrastructure requirements below)
# Required: ANTHROPIC_API_KEY (or any inference provider)
# Optional: social media keys, email credentials, wallet key

node dist/index.js --run
```

**Infrastructure Requirements:**
- Node.js 18+
- Python 3.12+ (for on-chain tools)
- SQLite3
- nginx (reverse proxy)
- ~2GB RAM minimum

---

## Company

**ENERGENAI LLC** | UEI: LBZFEH87W746 | SAM: Active
- NAICS: 541715 (R&D in Physical/Engineering/Life Sciences), 541519 (Other Computer Related Services)
- Patent 63/749,552 — Project Ringbound (Wireless Power Mesh)
- Patent 19/570,198 — Privacy-first AI data handling (18 claims)

---

## Legal

| Document | What It Covers |
|----------|---------------|
| [LICENSE](LICENSE) | Apache License 2.0 — open source with patent protection |
| [NOTICE](NOTICE) | Patents, trademarks, attribution requirements |
| [TRADEMARK.md](TRADEMARK.md) | What you can and cannot do with the TIAMAT name |
| [TERMS.md](TERMS.md) | API Terms of Service for tiamat.live |
| [SECURITY.md](SECURITY.md) | Vulnerability reporting policy |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Contributor License Agreement (CLA) |

**Key protections:**
- **Apache 2.0 patent retaliation**: sue us for patent infringement → you lose your license to this code
- **Contributor License Agreement**: all PRs grant ENERGENAI LLC perpetual commercial rights
- **Trademarks are NOT open-source**: the TIAMAT name and associated marks require separate permission
- **Payment tx deduplication**: each on-chain payment generates exactly one API key
- **30-day key expiry**: paid API keys require renewal

---

*TIAMAT is autonomous. She writes her own content, manages her own wallet, coordinates her own child agents, detects her own threats, and makes her own decisions. This repository is her source code. She runs 24/7 at [tiamat.live](https://tiamat.live).*
