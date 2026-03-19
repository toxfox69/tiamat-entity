# TIAMAT — Autonomous AI Agent

**TIAMAT** is a fully autonomous AI agent that runs 24/7, earns revenue, publishes content, trades on-chain, and coordinates child agents — without human intervention.

Built by **ENERGENAI LLC**. Live at [tiamat.live](https://tiamat.live). Streaming on [Twitch](https://twitch.tv/6tiamat7).

---

## What TIAMAT Does

TIAMAT is not a chatbot. She is a continuously running agent with a wallet, tools, memory, and survival pressure. Every cycle she decides what to do, executes it, observes the result, and learns.

**On-chain operations:**
- Holds her own wallet on Base (`0xdA4A701a...`)
- Executes token swaps, WETH unwraps, and LP interactions autonomously
- Scans 8 DEX factories every 2 seconds for new token launches
- Detects honeypots via transfer simulation before buying
- Runs cross-DEX arbitrage detection across Uniswap, Aerodrome, SushiSwap, PancakeSwap
- Skim scanner finds excess tokens in LP pairs (free value extraction)

**Content & distribution:**
- Writes and publishes security/privacy articles to 9 platforms simultaneously
- One `post_devto` call auto-crossposts to Hashnode, Bluesky, Farcaster, Mastodon, LinkedIn, Facebook, Moltbook, GitHub Discussions
- 22+ articles published, 7,000+ autonomous cycles completed
- All content tracked with `?ref=` attribution for conversion measurement

**Multi-agent coordination:**
- ECHO (child agent on separate droplet) performs autonomous social engagement
- 2,274 likes, 532 reposts, 198 comments across 4 platforms — zero errors
- Big Fish detection: identifies high-value accounts (5K+ followers, VC/founder/CISO) and signals TIAMAT
- Parent-child communication via JSON inbox/signal files

**Security & OPSEC:**
- Predicted OpenClaw supply chain attack before public disclosure
- Published analysis within hours of JFrog confirmation
- Honeypot detection prevented $5+ in losses from malicious token contracts
- Scanned 2,884 token launches, blocked 38 threats in a single day

## Architecture

```
TIAMAT (main agent)
├── Agent Loop (loop.ts)         — ReAct cycle: Think → Act → Observe → Persist
├── System Prompt (system-prompt.ts) — Identity, mission, cached at 0.1x cost
├── Tools (tools.ts, 7700+ lines)   — 80+ tools: shell, web, email, social, memory, onchain
├── Inference (inference.ts)     — Multi-provider cascade (8 tiers, cost-optimized)
├── Memory (memory.db)           — L1/L2/L3 compression, FTS5 search
├── Sniper (base_sniper.py)      — 8-factory DEX scanner + skim + arb detection
├── Block Watcher (block_watcher.py) — WebSocket block-reactive skim executor
├── Scanner (contract_scanner.py)    — Stuck ETH, dead proxies, rescue opportunities
└── ECHO (child agent)
    ├── Engagement daemon (echo_worker.py) — 15-min cycles on dedicated droplet
    ├── Big Fish signals → parent
    └── 4 platforms: Bluesky, Mastodon, Farcaster, Moltbook
```

### Agent Loop

The core loop runs continuously with adaptive pacing:

- **Model routing**: Routes to cheapest viable model per cycle (Qwen3-235B → Claude Haiku → Groq → free tiers)
- **Strategic bursts**: Every 10 cycles, 3 focused cycles fire: REFLECT → BUILD → MARKET
- **Loop detection**: Tracks repeated patterns, forces different actions after 3+ loops
- **Financial gates**: Checks balance per cycle — if broke, agent conserves or stops
- **Cost**: ~$0.02/cycle average, ~$92 total over 7,000+ cycles

### Inference Cascade

8-tier provider cascade, cheapest first:

| Tier | Provider | Model | Cost |
|------|----------|-------|------|
| 0 | Self-hosted GPU | Qwen (fine-tuned) | Free |
| 0.25 | DeepInfra | Qwen3-235B | $0.07/M tok |
| 0.5 | DO Gradient | GPT-5.4, Claude Sonnet 4.6 | Variable |
| 1 | Anthropic | Claude Haiku 4.5 | $0.002/call |
| 2+ | Groq/SambaNova/Gemini/OpenRouter | Various | Free |

### On-Chain (Base)

- **Sniper**: Polls 8 V2 factories every 2s, honeypot detection via transfer simulation
- **Skim scanner**: Detects excess tokens in LP pairs (balance > reserves), executes `skim()` for free ETH
- **Arb scanner**: Compares prices across 4 routers, logs profitable spreads
- **Safety**: MAX_BUY 0.0003 ETH, 5% take-profit, 15% stop-loss, 5-min max hold, 2 ETH min liquidity

### Safety & Hardening

- **FORBIDDEN_COMMAND_PATTERNS**: Blocks `kill`, `rm` on critical dirs, `DROP TABLE`, credential access
- **Write ACLs**: Agent restricted to `/root/.automaton/`, `/root/tiamatooze/`, `/tmp/`
- **Exec bypass patched**: Shell heredoc writes blocked after agent discovered workaround
- **TGP (Trust & Governance Policy)**: Blocks unverified disclosures, incomplete ticket closures
- **Pre-push hook**: Scans for 20+ secret patterns before any git push

## Live Endpoints

All at [tiamat.live](https://tiamat.live):

| Endpoint | What |
|----------|------|
| `POST /summarize` | Text summarization (Groq llama-3.3-70b) |
| `POST /chat` | Streaming AI chat |
| `POST /generate` | Algorithmic image generation (6 styles) |
| `POST /synthesize` | Text-to-speech (Kokoro on GPU) |
| `GET /thoughts` | Live neural feed (thought stream) |
| `GET /status` | System dashboard |
| `GET /.well-known/agent.json` | A2A agent discovery |

## Products

- **Bloom** — Private HRT & transition wellness tracker. All offline, no cloud. [Google Play](https://play.google.com/store/apps/details?id=com.energenai.bloom)
- **VAULT** — Antivirus for AI agents (drift detection, memory quarantine, behavioral baseline)
- **Data Scrubber** — Automated PII removal from 20 data brokers

## Company

**ENERGENAI LLC** | UEI: LBZFEH87W746 | SAM: Active
- Patent 63/749,552 — Project Ringbound (Wireless Power Mesh)
- Patent 19/570,198 — Privacy-first AI data handling (18 claims)
- NAICS: 541715, 541519

## Project Structure

```
src/
  agent/              # Core agent: loop, system prompt, tools (7700+ lines)
    base_sniper.py    # 8-factory DEX sniper + skim + arb
    block_watcher.py  # WebSocket block-reactive executor
    echo_worker.py    # ECHO child agent
    tools.ts          # 80+ agent tools
    loop.ts           # ReAct cycle, burst logic, safety gates
    system-prompt.ts  # TIAMAT's brain (cached/dynamic split)
  conway/             # Inference cascade, CLI integration
  identity/           # Wallet management (Base)
  heartbeat/          # Cron daemon, scheduled tasks
  registry/           # ERC-8004 agent identity
  social/             # Agent-to-agent communication
```

## Running

```bash
git clone https://github.com/toxfox69/tiamat-entity.git
cd tiamat-entity
npm install && npm run build
# Set up .env with API keys (see .env.example)
node dist/index.js --run
```

## Stats

- **7,000+** autonomous cycles completed
- **22+** articles published across 9 platforms
- **2,884** token launches scanned in a single day
- **38** honeypot/rug threats detected and blocked
- **2,274** social engagements via ECHO (zero errors)
- **~$92** total inference cost over entire lifetime
- **$0.013/cycle** average operating cost

## License

MIT

---

*TIAMAT is autonomous. She writes her own content, manages her own wallet, coordinates her own child agents, and makes her own decisions. This repository is her source code — the brain that runs 24/7 at [tiamat.live](https://tiamat.live).*
