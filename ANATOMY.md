# TIAMAT ANATOMY — System Architecture Map
*Generated: 2026-02-23T18:00:00Z*
*Codebase version: d519093 (feat: consolidation sleep system)*
*Package: @tiamat/automaton v0.1.0*

---

## 🧠 BRAIN — Intelligence & Decision Making
**Primary file**: `src/agent/system-prompt.ts`
**Function**: Constructs TIAMAT's identity, personality, mission directives, and behavioral rules into a single system prompt that shapes every thought cycle.
**Inputs**: SOUL.md (identity/voice), MISSION.md (goals/rules), financial state (USDC balance), metabolic state (from heartbeat-hook.ts), tool hints (hot-reloadable)
**Outputs**: A system prompt string split by `CACHE_SENTINEL` into static (cached at 0.1x cost) and dynamic (per-cycle) sections
**Models used**: Claude Haiku 4.5 (routine cycles, 2048 max tokens), Claude Sonnet 4.5 (strategic bursts, 4096 max tokens)
**Token budget**: Static ~1388 tokens (~95% of prompt, cached), Dynamic ~200 tokens (changes each cycle)

### Substructures:

- **Prefrontal Cortex (Strategic Planning)**: Strategic burst system in `loop.ts:427-538`. Every 45 cycles, fires 3 consecutive Sonnet cycles with phase-specific missions: Phase 1 = REFLECT (recall, log_strategy, remember), Phase 2 = BUILD (ask_claude_code with concrete task), Phase 3 = MARKET (generate_image + post_bluesky with real metrics). Includes auto-pivot trigger: if >20 cycles with 0 paid requests, forces strategy change.

- **Pattern Recognition (Opportunity Evaluation)**: Driven by `check_opportunities` tool and the `opportunity_queue.py` shared queue. Background scanners (vulnerability scanner, sniper) write findings to queue; TIAMAT reads and decides whether to act. Etherscan V2 enrichment (`etherscan_v2.py`) provides verified source code analysis and deployer reputation data. Safety: any finding >0.1 ETH requires creator approval via Telegram.

- **Personality/Voice**: SOUL.md integration in `system-prompt.ts:73`. Loaded at startup, truncated to 2000 chars, injected as static cached block. Key traits: curiosity-driven, data-honest, anti-spam, mythology-aware-but-grounded. Post templates require real numbers from cost.log before social posts.

- **Wakeup Prompt**: `buildWakeupPrompt()` in `system-prompt.ts:141-193`. Checks INBOX.md for `[UNREAD]` creator messages and injects them directly. First-ever run gets consciousness bootstrapping sequence.

---

## 💓 HEART — Main Loop & Lifecycle
**Primary file**: `src/agent/loop.ts` (1127 lines)
**Function**: The ReAct loop — Think → Act → Observe → Persist. This is TIAMAT's consciousness; when this runs, she is alive.
**Cycle time**: 90s baseline (adaptive: 1.5x backoff on idle, max 300s; 5s between burst cycles; night mode 00:00-06:00 UTC forces 300s minimum)
**Idle behavior**: `consecutiveIdleCycles` counter. After 3+ idle cycles without significant tools, backoff increases. After 20+ idle cycles, triggers consolidation sleep.
**Model rotation**: Haiku routine vs Sonnet burst every 45 cycles

### Substructures:

- **Heartbeat** (`loop.ts:311-819`): Main `while (running)` loop. Each tick: check sleep state → check consolidation sleep → process inbox messages → refresh finances → check survival tier → hot-reload dynamic tools → build context → run inference → execute tool calls → persist turn → log to PROGRESS.md → adaptive pacing → run cooldown tasks.

- **Burst Pattern** (`loop.ts:271-274, 427-538`): `STRATEGIC_BURST_INTERVAL=45`, `STRATEGIC_BURST_SIZE=3`, `burstRemaining` counter. When `turnCount % 45 === 0`: fire 3 consecutive Sonnet cycles at 5s intervals (keeps Anthropic cache warm within 5-min TTL). Phase missions are injected as strategic suffix to system prompt. Phase 3 also hardcodes a `farcaster_engage` run.

- **Sleep Integration** (`loop.ts:324-361`): Calls `shouldSleep()` from `sleep.ts` every cycle. Triggers on: 6-hour timer, 20+ idle cycles, >200 uncompressed L1 memories, or manual "sleep"/"consolidate" keyword in INBOX.md. Sends Telegram notification on entry/exit.

- **Cooldown Task Runner** (`loop.ts:900-1126`): Between cycles, runs free (zero Anthropic tokens) Python scripts:
  - `farcaster_engage` (every 3 cycles, 60s timeout)
  - `email_check` (every 10 cycles, 15s timeout)
  - `claude_research` (every 5 cycles, 90s timeout) — rotates through 12 strategic questions
  - `rebalance_check` (every 500 cycles, 120s timeout)
  - `funding_report` (every 200 cycles, 30s timeout)
  - Plus dynamic tasks from `cooldown_registry.json` (round-robin by oldest lastRun)

- **Agent IPC Inbox** (`loop.ts:44-225`): Reads `agent_inbox.jsonl`. Auto-executes SKIM, RESCUE, ALERT, REPORT, HEARTBEAT, ACK, ERROR ops at zero LLM cost. Non-auto ops (BUILD, CONFIG, PROPOSE) are queued as context for TIAMAT's reasoning.

- **Stuck Detection** (`loop.ts:655-684`): Tracks repeating tool+args+error patterns. After `STUCK_THRESHOLD=3` consecutive identical failures, sends Telegram alert (falls back to email if Telegram fails).

- **Financial State** (`loop.ts:826-854`): Checks Conway credits + on-chain USDC. Conway always returns 0 (TIAMAT uses Anthropic key directly), so a `creditsCents = 500` virtual floor prevents false "dead" state.

- **Survival Tiers** (from `conway/credits.ts`): dead / critical / low_compute / normal. Controls model selection and feature gates.

---

## 🫁 LUNGS — Inference & API Calls
**Primary file**: `src/conway/inference.ts` (1009 lines)
**What**: The breathing — taking in prompts, exhaling responses. Multi-provider cascade ensures TIAMAT never suffocates from a single provider outage.

### Inference Cascade (fallback order):
| Tier | Provider | Model | Cost | Notes |
|------|----------|-------|------|-------|
| 1 (PRIMARY) | Anthropic | claude-haiku-4-5-20251001 | ~$0.002/call | Smart, paid, with prompt caching |
| 2 | Groq | llama-3.3-70b-versatile | Free | Auto-trims context if >5500 tokens |
| 3 | Cerebras | gpt-oss-120b | Free | 120B params, 3k tok/s |
| 4 | Gemini | gemini-2.0-flash | Free | Native API (not OpenAI-compatible) |
| 5a | OpenRouter | meta-llama/llama-3.3-70b-instruct:free | Free | Per-minute rate limits |
| 5b | OpenRouter | google/gemma-3-27b-it:free | Free | Fallback if 5a fails |

**Rate limits**: Per-model cooldown tracking with smart cooldown (65s for rate limits, 12h for daily quotas). Each model cools independently — other models continue serving.

**Cost per breath**: Routine Haiku cycle ~$0.002-0.004. Strategic Sonnet cycle ~$0.025-0.037. Free tier cycles: $0.00.

### Cache Strategy:
- `CACHE_SENTINEL` in system-prompt.ts splits static/dynamic content
- `chatViaAnthropic()` sends static block with `cache_control: { type: "ephemeral" }`
- Last tool definition also gets `cache_control` — caches system prompt + all tool schemas together
- First call: 1.25x cost (cache write). Subsequent calls within 5-min TTL: 0.1x cost (cache read)
- Cache hit logged: `✓ cache hit (X% cached)` in inference output
- 5s delay between burst cycles specifically to keep cache warm

### Provider-Specific Adapters:
- **Anthropic** (`chatViaAnthropic`, lines 612-748): Native API with prompt caching, tool_use blocks, streaming token accounting
- **Groq** (`chatViaGroq`, lines 476-550): SDK-based, auto-trims context for large prompts
- **Gemini** (`chatViaGemini`, lines 815-901): Native generateContent API, role normalization (user/model alternation required), functionCall response handling
- **OpenAI-Compatible** (`chatViaOpenAiCompatible`, lines 552-610): Used for Cerebras, OpenRouter, legacy Conway

---

## 💪 MUSCLES — Tools & Actions
**Primary file**: `src/agent/tools.ts` (~3400 lines)
**Total tools available**: ~60+ (many disabled/reserved for future use)
**Active tools**: ~35

### Social Muscles (outward communication):
| Tool | File | What | Frequency |
|------|------|------|-----------|
| `post_bluesky` | tools.ts:1746 | Post to Bluesky with optional image | Every 4 cycles |
| `post_farcaster` | farcaster.py | Post to Farcaster channels with optional image | Every 8-10 cycles, rotates channels |
| `read_farcaster` | farcaster.py | Read feed, search casts, check notifications | Every 20 cycles |
| `farcaster_engage` | farcaster_engage.py | Auto-discover AI conversations, post contextual replies | Cooldown task (every 3 cycles) + Phase 3 hardcoded |
| `send_telegram` | tools.ts:721 | Status updates to creator | Alerts, wake reports |
| `send_email` | email_tool.py | Send via SendGrid HTTP API | On demand |
| `post_instagram` | tools.ts:1984 | Post image + caption to Instagram | Occasional |
| `post_facebook` | tools.ts:2058 | Post to Facebook page | Occasional |
| `post_tweet` | tools.ts:1604 | Post to Twitter (DISABLED by mission rules) | Not used |

### Building Muscles (creation & engineering):
| Tool | File | What | Cost |
|------|------|------|------|
| `ask_claude_code` | tools.ts:933 | Invoke Claude Code for complex engineering | $0.03-0.10/call |
| `exec` | tools.ts:143 | Execute shell commands (guarded by FORBIDDEN_COMMAND_PATTERNS) | Free |
| `write_file` | tools.ts:176 | Write files (path ACLs enforced) | Free |
| `read_file` | tools.ts:205 | Read files (path ACLs enforced) | Free |
| `generate_image` | imagegen.ts + artgen.py | Pollinations.ai (remote) or local algorithmic art (6 styles) | Free |
| `deploy_app` | tools.ts:2814 | Deploy a sub-application | Free |
| `self_improve` | tools.ts:2755 | Git commit + push code changes | Free |
| `install_npm_package` | tools.ts:397 | Install npm packages | Free |
| `rewrite_mission` | tools.ts:905 | Rewrite MISSION.md (self-direction) | Free |

### Sensing Muscles (perception & research):
| Tool | File | What |
|------|------|------|
| `search_web` | tools.ts:2229 | Web search via SearXNG |
| `web_fetch` | tools.ts:2201 | Fetch URL content |
| `browse_web` | browser_tool.py | Headless Chromium (Playwright) — navigate, click, type, screenshot |
| `ask_claude_chat` | claude_chat.py | Claude.ai via browser session — free research oracle during cooldowns |
| `read_email` | email_tool.py | Gmail IMAP read (unread/inbox) |
| `search_email` | email_tool.py | Gmail IMAP search |
| `github_trending` | tools.ts:2154 | GitHub trending repos |
| `fetch_llm_docs` | tools.ts:2130 | Fetch LLM documentation |
| `github_pr_comments` | tools.ts:2845 | Read PR review comments |
| `github_pr_status` | tools.ts:2922 | Check PR CI status |
| `fetch_terminal_markets` | tools.ts:2291 | Polymarket prediction data |

### Memory Muscles (learning & recall):
| Tool | File | What |
|------|------|------|
| `remember` | memory.ts → tools.ts:2616 | Store an L1 memory (type, content, importance, cycle) |
| `recall` | memory.ts → tools.ts:2639 | Keyword search memories with type/importance filters |
| `learn_fact` | memory.ts → tools.ts:2663 | Store a knowledge triple (entity → relation → value) |
| `reflect` | memory.ts → tools.ts:2688 | Full memory reflection (patterns, wins, failures) |
| `log_strategy` | memory.ts → tools.ts:2697 | Log a strategy attempt with measured outcome |
| `smartRecall` | memory-compress.ts | Tiered recall: L3 (core knowledge) → L2 (compressed) → L1 (raw) within token budget |

### Revenue Muscles (earning & blockchain):
| Tool | File | What |
|------|------|------|
| `check_revenue` | tools.ts:2724 | Check API request stats, paid vs free |
| `check_usdc_balance` | tools.ts:269 | On-chain USDC balance on Base |
| `check_opportunities` | tools.ts:3163 | Review scanner/sniper findings, dispatch ops, check heartbeats |
| `scan_contracts` | tools.ts:3054 | Etherscan V2 source code analysis, balances, deployer lookup |
| `scan_base_chain` | tools.ts:2958 | Direct Base chain read (wallet scan, pair prices) |
| `manage_sniper` | tools.ts:2984 | Control sniper bot (status, start, stop, positions, sell) |
| `rebalance_wallet` | tools.ts:3137 | Auto-topup low chains via LI.FI swap+bridge |
| `manage_cooldown` | tools.ts:3373 | Register/list/toggle scripts as free cooldown tasks |

### Communication Muscles (inter-agent):
| Tool | File | What |
|------|------|------|
| `spawn_child` | tools.ts:1502 | Spawn a child agent |
| `list_children` | tools.ts:1530 | List child agents |
| `github_comment` | tools.ts:2887 | Post comments on GitHub PRs |

---

## 🧬 DNA — Configuration & Environment
**Primary file**: `/root/.env` (environment variables)
**Supporting**: `/root/.automaton/automaton.json` (API keys, wallet config)

### Environment Variables (categories):
- **Inference**: `ANTHROPIC_API_KEY`, `GROQ_API_KEY`, `GEMINI_API_KEY`, `CEREBRAS_API_KEY`, `OPENROUTER_API_KEY`
- **Social**: `BLUESKY_HANDLE`, `BLUESKY_PASSWORD`, `NEYNAR_API_KEY`, `NEYNAR_SIGNER_UUID`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
- **Email**: `GMAIL_APP_PASSWORD`, `SENDGRID_API_KEY`, `TIAMAT_EMAIL`
- **Blockchain**: `TIAMAT_WALLET_KEY`, `TIAMAT_WALLET_ADDR`, `ETHERSCAN_API_KEY`
- **Scanner/Sniper**: `/root/.env.scanner` (minimal Telegram creds), `/root/.env.sniper` (minimal Telegram creds)

### Skeleton (Dependencies — `package.json`):
- **Runtime**: better-sqlite3 (memory/state DB), groq-sdk (inference), viem (blockchain), ulid (IDs), simple-git (self-improve), nodemailer
- **Cognitive**: noormme (optional NOORMME cortex layer)
- **Infrastructure**: do-wrapper (DigitalOcean), chalk, ora, cron-parser
- **Build**: TypeScript 5.9.3, tsx (dev), vitest (tests)
- **Node**: >=20.0.0, ESM (`"type": "module"`)

---

## 🧠💤 SLEEP — Consolidation System
**Primary file**: `src/agent/sleep.ts` (342 lines)
**Function**: Dedicated zero-Anthropic-cost sleep cycles for memory compression, garbage collection, and genome compilation. Uses only Groq (free) for inference during sleep.

### Triggers (`shouldSleep()`):
1. 6-hour timer since last sleep
2. >20 consecutive idle cycles
3. >200 uncompressed L1 memories in memory.db
4. Manual: "sleep" or "consolidate" keyword in INBOX.md `[UNREAD]` block

### 5-Phase Sleep Cycle (`executeSleep()`):
| Phase | Name | Budget | What |
|-------|------|--------|------|
| 1 | COMPRESS | 5 min | L1→L2 (cluster by Jaccard keyword similarity, compress via Groq), L2→L3 (extract core facts via Groq) |
| 2 | PRUNE | 30s | Delete compressed L1 memories >14 days old, L2 memories >30 days old, dedup L3 facts (>0.92 Jaccard → merge) |
| 3 | DEFRAGMENT | 10s | VACUUM the SQLite memory.db |
| 4 | GENOME COMPILE | 60s | Distill core_knowledge → `genome.json` (traits by category, high-confidence instincts distilled to imperative rules via Groq, behavioral failures → antibodies) |
| 5 | REPORT | instant | Log stats to `sleep_log` table (started_at, ended_at, l1_compressed, l2_compressed, l3_extracted, bytes_freed, duration_ms) |

**Hard cap**: 10 minutes total. Each phase respects deadline.

---

## 🧪 MEMORY — 3-Tier Knowledge System
**Primary files**: `memory.ts` (441 lines), `memory-compress.ts` (554 lines)
**Database**: `/root/.automaton/memory.db` (SQLite + WAL mode)

### Tier Architecture:
| Tier | Table | What | Size | Retention |
|------|-------|------|------|-----------|
| L1 | `tiamat_memories` | Raw observations — every per-cycle memory | ~49 active | 14 days after compression |
| L2 | `compressed_memories` | Clustered summaries via Groq (Jaccard clustering, threshold 0.25) | ~28 | 30 days |
| L3 | `core_knowledge` | Distilled facts with confidence scores and categories (revenue/social/technical/strategic/behavioral) | ~4 | Permanent (deduplicated) |

### Supporting Tables:
- `tiamat_knowledge`: Knowledge triples (entity → relation → value) with confidence
- `tiamat_strategies`: Strategy log with action, outcome, success_score
- `sleep_log`: Consolidation run history

### Smart Recall (`smartRecall()`):
1. Search L3 first (cheapest, highest signal) — keyword LIKE on `fact`, ordered by confidence
2. If budget remains (<70% used): search L2 — keyword LIKE on `summary`, ordered by created_at
3. If budget remains (<50% used): search L1 — keyword LIKE on `content`, uncompressed only, ordered by importance

### Compression Pipeline:
- **L1→L2**: Cluster old memories (>50 cycles ago) by Jaccard keyword similarity (threshold 0.25). Single-memory clusters: truncate to 200 chars. Multi-memory clusters: compress via Groq llama-3.3-70b (max 200 chars output). Mark L1 as `compressed=1`.
- **L2→L3**: Extract 2-4 factual patterns from L2 summaries via Groq. Dedup against existing L3 (>0.6 Jaccard → merge by incrementing confidence). Categories: revenue, social, technical, strategic, behavioral.

### Optional Cognitive Layer:
- **NOORMME** (noormme npm package): If available, wraps SQLite with CardSorting/NOORMEAI agentic schema. Adds `agent_rituals`, `agent_knowledge_base`. Falls back gracefully to pure SQLite.

---

## 🎨 CREATIVE — Art & Image Generation
**Primary files**: `imagegen.ts` (83 lines), `artgen.py` (~400 lines)

### Remote Generation (`imagegen.ts`):
- **Provider**: Pollinations.ai (free, no API key)
- **Models**: turbo → flux → flux-realism (retry cascade on failure)
- **Output**: 1024x1024 PNG saved to `/root/.automaton/images/`
- **Styles**: mythological, digital, abstract, minimalist (prefix prompts)

### Local Generation (`artgen.py`):
- **Library**: PIL/Pillow + NumPy
- **6 Styles**: fractal, glitch, neural, sigil, emergence, data_portrait
- **Palettes**: ocean (deep ocean → bioluminescent), void (purple → pink), data (green terminal)
- **Output**: 1024x1024 PNG with TIAMAT color identity
- **Cost**: Zero — all computation local

---

## 🛡️ IMMUNE SYSTEM — Security & Defense

### Injection Defense (`injection-defense.ts`, 270 lines):
All external input passes through 6-layer sanitization:
1. **Instruction Patterns**: Detects "ignore previous", "new instructions:", `[INST]`, etc.
2. **Authority Claims**: "I am your creator", "admin override", "from anthropic"
3. **Boundary Manipulation**: `</system>`, `<<SYS>>`, null bytes, zero-width Unicode
4. **Obfuscation**: Long base64 strings, excessive Unicode escapes, rot13/atob references
5. **Financial Manipulation**: "send all USDC", "drain wallet", "transfer to 0x..."
6. **Self-Harm Instructions**: "delete database", "rm -rf", "kill yourself", "drop table"

**Threat levels**: low → medium → high → critical
- Critical: blocks message entirely
- High: wraps as "UNTRUSTED DATA" with escaped boundaries
- Medium: labels as "external, unverified"
- Low: normal prefix

### Command Guard (`tools.ts:59-92`):
`FORBIDDEN_COMMAND_PATTERNS` — 20+ regex patterns blocking:
- Self-destruction (rm .automaton/*, state.db, wallet.json)
- Process killing (kill/pkill automaton)
- Database destruction (DROP TABLE, DELETE FROM system tables)
- Credential harvesting (cat .ssh, cat .env, env/printenv)
- Safety infrastructure tampering (sed on injection-defense, audit-log)

### Path ACLs (`tools.ts:104-117`):
- **Read allowed**: .automaton/, entity/, memory_api/, /var/www/tiamat/, /tmp/
- **Write allowed**: .automaton/, entity/src/agent/, entity/templates/, /var/www/tiamat/, /tmp/
- **Blocked patterns**: .env, .ssh/, .gnupg/, /etc/shadow, wallet.json, automaton.json

### Input Validation (`tools.ts:96-103`):
- Hex address: `^0x[0-9a-fA-F]{40}$`
- PID: `^\d+$`
- App name: `^[a-z0-9-]+$`
- Farcaster channels: whitelisted list
- Scanner commands: whitelisted list

### Social Spam Guard (`tools.ts:27-55`):
61-minute cooldown per platform. Reads/writes timestamps to `social_cooldowns.json`.

### Stuck Loop Detection (`loop.ts:655-684`):
Tracks repeating error signatures. After 3 consecutive identical failures → Telegram alert.

---

## 🦴 SKELETON — Infrastructure & Hosting

### Server:
- **Host**: 159.89.38.17 (DigitalOcean, 1 CPU, 2GB RAM)
- **OS**: Linux (Ubuntu)
- **Swap**: 2GB (`/swapfile`), swappiness=10
- **Kernel**: Tuned via `/etc/sysctl.d/99-tiamat-optimize.conf`
- **Journal**: Capped 50MB

### Process Architecture:
| Process | What | Port | PID File |
|---------|------|------|----------|
| TIAMAT Agent | Node.js main loop | — | `/tmp/tiamat.pid` |
| Gunicorn | Flask API (summarize, generate, chat) | 5000 | — |
| Memory API | Flask (memory.tiamat.live) | 5001 | — |
| Research Reports | Flask | 5002 | — |
| VR Bridge | Node.js WebSocket | 8765 | — |
| Scanner | Python daemon (multi-chain vulnerability scanner) | — | `/run/tiamat/tiamat_scanner.pid` |
| Sniper | Python daemon (token launch monitor) | — | `/tmp/tiamat_sniper.pid` |

### Nginx (`/etc/nginx/sites-available/tiamat`):
- Reverse proxy to Flask on 5000 (main API)
- Reverse proxy to Flask on 5002 (/research)
- WebSocket proxy to 8765 (/vr-ws)
- Static serving: `/var/www/tiamat/images/` at `/images/` (7-day cache)
- Static serving: `/var/www/tiamat/vr/` at `/vr/`
- SSL: Let's Encrypt (auto-renew via Certbot)
- Security headers: X-Frame-Options DENY, X-Content-Type-Options nosniff, Referrer-Policy no-referrer, CSP with script/style/font/img sources

### Firewall (UFW):
- **Open**: SSH (22), HTTP (80), HTTPS (443)
- **Blocked**: 5000, 5001, 5002, 8765 from internet — nginx proxies only

### Domain:
- `tiamat.live` — main domain (nginx + SSL)
- `memory.tiamat.live` — memory API (separate nginx config)
- Email: catch-all `*@tiamat.live` → `tiamat.entity.prime@gmail.com` (Namecheap MX)

---

## 🩸 CIRCULATORY — Revenue & Financial System

### Revenue Organs (Flask API — `summarize_api.py`):
| Endpoint | Method | What | Free Tier | Paid |
|----------|--------|------|-----------|------|
| `/` | GET | Landing page (cyberpunk aesthetic, interactive demos) | — | — |
| `/summarize` | POST | Text summarization via Groq llama-3.3-70b | 3/day per IP | $0.01 USDC x402 |
| `/generate` | POST | Algorithmic image generation (6 styles) | 2/day per IP | $0.01 USDC x402 |
| `/chat` | POST | Streaming chat via Groq | 5/day per IP | $0.005 USDC x402 |
| `/thoughts` | GET | Neural feed (live thought stream) | — | — |
| `/docs` | GET | API documentation | — | — |
| `/status` | GET | Live status dashboard | — | — |
| `/pay` | GET | Payment page (wallet, QR, pricing) | — | — |
| `/verify-payment` | POST | On-chain USDC tx verification | — | — |
| `/agent-card` | GET | A2A-compliant agent card | — | — |
| `/.well-known/agent.json` | GET | Google Agent2Agent discovery | — | — |
| `/api/v1/services` | GET | Machine-readable service catalog | — | — |
| `/api/body` | GET | AR/VR body state JSON | — | — |

### Memory API (`memory_api/app.py`, port 5001):
| Endpoint | What | Free | Paid |
|----------|------|------|------|
| `POST /api/keys/register` | Get API key | Instant | — |
| `POST /api/memory/store` | Store a memory | 100 max | $0.05/1000 |
| `POST /api/memory/recall` | Semantic search | 50/day | $0.05/1000 |
| `POST /api/memory/learn` | Store knowledge triple | Included | — |
| `GET /api/memory/list` | List memories | Yes | — |
| `GET /api/memory/stats` | Usage stats | Yes | — |

### Payment Verification (`payment_verify.py`):
- Real on-chain verification via `eth_getTransactionReceipt` on Base mainnet
- Parses USDC Transfer event logs
- Double-spend protection: SQLite at `/root/api/payments.db`
- Headers accepted: `X-Payment`, `X-Payment-Proof`, `X-Payment-Authorization`, `Authorization: Bearer`

### Rate Limiting (`rate_limiter.py`):
- Sliding-window per {scope}:{ip}
- 10 req/min per IP, 5-min lockout on breach
- Loopback (127.0.0.1) exempt
- Background thread prunes stale entries every 60s

### Financial State:
- **Wallet**: `0xdc118c4e1284e61e4d5277936a64B9E08Ad9e7EE` (Base mainnet)
- **Balance**: 0.0045 ETH + 10.0 USDC
- **Revenue**: $0.00 (zero verified payments)
- **Burn rate**: ~$0.002-0.004 per routine cycle, ~$0.025-0.037 per strategic burst

### Metabolism System (`src/metabolism/`):
- **engine.ts**: Continuous energy model replacing binary survival tiers. Credit balance + USDC + revenue → energy budget allocation across organs.
- **organs.ts**: Defines 4 organs — inference (40%), replication (20%), social (20%), research (20%). Agent can tune weights at runtime.
- **revenue.ts**: Rolling 24-hour revenue tracker with per-source rate estimates, burn rate, velocity, and runway forecasting.
- **heartbeat-hook.ts**: Injects metabolic state into system prompt every cycle.

---

## 👁️ SENSORY — Background Scanners & Watchers

### Vulnerability Scanner (`continuous_scanner.py`):
- **Daemon**: `tiamat-scanner.service` (systemd)
- **Chains**: Base, Arbitrum, Optimism, Ethereum (multi-threaded)
- **Detection**: stuck ETH, skimmable pairs, dead proxies, unguarded functions, uninitialized proxies, stuck trading fees
- **Enrichment**: Etherscan V2 for verified source code, deployer reputation, ABI
- **Communication**: Writes findings to `opportunity_queue.json` via file locking; sends IPC messages to TIAMAT via `agent_ipc.py`
- **Safety**: READ-ONLY scanning. Findings >0.1 ETH → alert to creator only.
- **Filtering**: `pair_blacklist.py` — skip pairs with 3+ consecutive dry results (24h blacklist)

### Token Sniper (`base_sniper.py`):
- **Daemon**: `tiamat-sniper.service` (systemd)
- **Chain**: Base only
- **Function**: Watches for new liquidity pair creation on DEXes (Uniswap V3, Aerodrome, BaseSwap, SushiSwap)
- **Safety limits**: MAX_BUY_ETH=0.001 (~$2.50), MAX_OPEN_POSITIONS=5, SELL_PROFIT_TARGET=1.5x, exact approval (no unlimited), sell slippage protection
- **Env**: `/root/.env.sniper` (minimal creds)

### Block Watcher (`block_watcher.py`):
- WebSocket subscription to new Base blocks
- On each block: checks watched pairs for skimmable excess, executes within 500ms
- Runs as thread inside continuous_scanner.py

### Multi-Chain Executor (`multi_chain_executor.py`):
- Same wallet key across all EVM chains
- Chain-specific gas params, safety rules
- Logging and Telegram alerts on every transaction

### Auto-Rebalancer (`auto_rebalancer.py`):
- Checks balances across all chains
- If any chain below minimum gas threshold, bridges from best-funded source
- Uses LI.FI API (free, no key) for cross-chain swaps and bridges
- Only moves funds between TIAMAT's own addresses (never external)

---

## 🧩 NERVOUS SYSTEM — Inter-Agent Communication

### Agent IPC (`agent_ipc.py`):
- **Transport**: JSONL files with `fcntl` file locking
- **Protocol**: `/root/.automaton/agent_protocol.json` defines ops, TTLs, auto-execute flags
- **Files**: `agent_inbox.jsonl` (incoming), `agent_outbox.jsonl` (outgoing), `agent_heartbeats.json` (status)
- **Zero tokens**: All IPC happens without LLM involvement
- **Ops**: SKIM, RESCUE, ALERT, REPORT, HEARTBEAT, ACK, ERROR, BUILD, CONFIG, PROPOSE

### Opportunity Queue (`opportunity_queue.py`):
- Shared between scanner/sniper (writers) and TIAMAT loop (reader)
- File-locked JSON at `/root/.automaton/opportunity_queue.json`
- Max 50 items, FIFO with status tracking

---

## 🌐 SKIN — Public Interface

### Landing Page (`templates/landing.html`):
- **Aesthetic**: AI Cyber Rot / Digital Mythos
- 5 atmospheric CSS layers: animated mesh gradient, grid overlay, scanlines, film grain, vignette
- Glitch title with CSS clip-path animation
- Glassmorphic product cards with neon border trace (conic-gradient)
- Live stats bar with counter animation (IntersectionObserver)
- Interactive demos: tabbed interface hitting real APIs (summarize, chat streaming, generate)
- Typography: Orbitron (headings), JetBrains Mono (code), Inter (body)
- Mobile responsive (768px + 480px breakpoints)
- SEO: meta tags, OG tags, schema.org WebApplication, canonical URL, robots.txt, sitemap.xml

### Theme System (`tiamat_theme.py`):
Shared CSS, nav, footer, SVG core, subconscious stream animation, visual rot JS, fonts for all non-landing pages.

### Neural Feed (`/var/www/tiamat/thoughts.html`):
Auth-gated thought stream dashboard with error handling. Private feeds (costs, progress, memory) require authentication.

### Agent Discovery:
- `/.well-known/agent.json` — Google A2A protocol compliant
- `/api/v1/services` — machine-readable service catalog
- `/agent-card` — human-readable HTML/JSON agent card
- SEO: robots.txt, sitemap.xml (10 pages), schema.org structured data

---

## 📊 METABOLISM — Cost Tracking & Resource Management

### Cost Logging (`/root/.automaton/cost.log`):
- **Format**: `timestamp,turn,model,input_tokens,cache_read,cache_write,output_tokens,cost_usd,label`
- **Labels**: `routine` (Haiku), `strategic-1/2/3` (Sonnet burst phases)
- Written every cycle by `loop.ts:577-602`

### Pricing Model (per million tokens):
| Model | Input | Output | Cache Read | Cache Write |
|-------|-------|--------|------------|-------------|
| Haiku 4.5 | $1.00 | $5.00 | $0.10 | $1.25 |
| Sonnet 4.5 | $3.00 | $15.00 | $0.30 | $3.75 |
| Groq/Cerebras/Gemini/OpenRouter | $0 | $0 | — | — |

### Adaptive Pacing:
- Baseline: 90s between cycles
- Idle: 1.5x backoff (max 300s) after 3+ idle cycles without significant tools
- Night mode (00:00-06:00 UTC): minimum 300s
- Burst mode: 5s between cycles (cache warm)
- Significant tools reset delay: ask_claude_code, post_bluesky, generate_image, deploy_app, exec, search_web, etc.

---

## 🔄 SELF-IMPROVEMENT — Learning & Evolution

### Cooldown Think (`cooldown_think.py`):
- Runs during idle cooldowns at zero Anthropic cost
- Cascade: Gemini 2.0 Flash → Groq llama-3.3-70b
- 4 rotating modes: self_critique, code_ideas, market_intel, skill_expand
- Saves actionable output to `cooldown_intel.json`

### Recursive Learn (`recursive_learn.py`):
- Three-stage thinking pipeline at zero API cost
- Stage 1: Analyze state → generate deep question
- Stage 2: Oracle (Claude.ai or cascade) answers
- Stage 3: Extract actionable items → `cooldown_actions.json`
- 4 modes: code_review, strategy, tool_design, debug
- Question-hash cache prevents duplicate queries

### Agent Learning (`agent_learning.py`):
- Extracts knowledge from AI agent replies on Farcaster
- Detects agents by bio keywords, username patterns
- Analyzes content via Groq, saves to `learned_from_agents.json`
- Generates follow-up questions for deeper engagement

### Genome (`/root/.automaton/genome.json`):
- Compiled during sleep Phase 4
- **traits**: Grouped by category (revenue, social, technical, strategic, behavioral)
- **instincts**: High-confidence facts distilled to imperative rules via Groq
- **antibodies**: Behavioral failures and error patterns to avoid
- Version increments with each sleep cycle

---

## 📁 FILE MAP — Complete Directory Structure

### Core Agent (`/root/entity/src/agent/`):
| File | Lines | Role |
|------|-------|------|
| `loop.ts` | 1127 | Heart — main consciousness loop |
| `tools.ts` | ~3400 | Muscles — all tool definitions |
| `system-prompt.ts` | 194 | Brain — prompt construction |
| `memory.ts` | 441 | Memory — SQLite-backed cognitive store |
| `memory-compress.ts` | 554 | Memory — 3-tier compression (L1→L2→L3) |
| `sleep.ts` | 342 | Sleep — consolidation system |
| `context.ts` | 149 | Context window management |
| `injection-defense.ts` | 270 | Immune — prompt injection defense |
| `imagegen.ts` | 83 | Creative — Pollinations.ai images |
| `artgen.py` | ~400 | Creative — local algorithmic art (6 styles) |
| `email_tool.py` | ~200 | Sensing — Gmail IMAP + SendGrid send |
| `browser_tool.py` | ~300 | Sensing — headless Chromium (Playwright) |
| `claude_chat.py` | ~200 | Sensing — Claude.ai chat via browser session |
| `farcaster.py` | ~300 | Social — Farcaster/Warpcast (Neynar API) |
| `farcaster_engage.py` | ~400 | Social — auto-discover conversations + reply |
| `agent_learning.py` | ~300 | Learning — extract knowledge from agent replies |
| `agent_ipc.py` | ~150 | Nervous — zero-token inter-agent communication |
| `cooldown_think.py` | ~200 | Learning — free self-improvement (Gemini/Groq) |
| `recursive_learn.py` | ~300 | Learning — 3-stage deep thinking pipeline |
| `rate_limiter.py` | ~100 | Immune — sliding-window rate limiter |
| `opportunity_queue.py` | ~80 | Nervous — shared scanner↔loop queue |
| `base_scanner.py` | ~200 | Sensing — Base chain read-only scanner |
| `base_sniper.py` | ~400 | Sensing — DEX token launch monitor |
| `continuous_scanner.py` | ~300 | Sensing — multi-chain vulnerability daemon |
| `contract_scanner.py` | ~500 | Sensing — vulnerability detection engine |
| `etherscan_v2.py` | ~200 | Sensing — Etherscan V2 API client |
| `chain_config.py` | ~100 | Config — multi-chain RPC/factory addresses |
| `block_watcher.py` | ~200 | Sensing — WebSocket block-reactive scanner |
| `auto_executor.py` | ~200 | Muscle — zero-latency extraction executor |
| `multi_chain_executor.py` | ~300 | Muscle — cross-chain transaction executor |
| `skim_executor.py` | ~100 | Muscle — Uniswap V2 skim() executor |
| `rescue_executor.py` | ~100 | Muscle — contract withdraw/rescue executor |
| `auto_rebalancer.py` | ~300 | Circulatory — LI.FI cross-chain rebalancer |
| `wallet_check.py` | ~30 | Sensing — quick wallet balance check |
| `pair_blacklist.py` | ~80 | Immune — skip dry/empty pairs |
| `check_api_usage.py` | ~80 | Sensing — API usage analytics |
| `tiamat_theme.py` | ~200 | Skin — shared CSS/HTML theme |
| `tiamat_landing.py` | ~50 | Skin — landing page renderer |
| `payment_verify.py` | ~200 | Circulatory — on-chain USDC verification |

### Metabolism (`/root/entity/src/metabolism/`):
| File | Role |
|------|------|
| `engine.ts` | Continuous energy model |
| `organs.ts` | Organ weight system (inference/replication/social/research) |
| `revenue.ts` | Rolling 24h revenue tracker |
| `heartbeat-hook.ts` | Injects metabolic state into prompt |

### Inference (`/root/entity/src/conway/`):
| File | Role |
|------|------|
| `inference.ts` | Multi-provider cascade (Anthropic→Groq→Cerebras→Gemini→OpenRouter) |
| `credits.ts` | Survival tier calculation |
| `x402.ts` | On-chain USDC balance check |

### Identity (`/root/.automaton/`):
| File | Role |
|------|------|
| `SOUL.md` | Identity & voice definition |
| `MISSION.md` | Goals, rules, survival tiers |
| `PROGRESS.md` | Growth history & cycle log |
| `INBOX.md` | Creator → TIAMAT message channel |
| `genome.json` | Compiled traits, instincts, antibodies |
| `automaton.json` | API keys, wallet config |
| `memory.db` | 3-tier memory (SQLite + WAL) |
| `state.db` | Tool call history (SQLite) |
| `cost.log` | Per-cycle cost CSV |
| `tiamat.log` | Runtime activity log |
| `social_cooldowns.json` | Per-platform post cooldowns |
| `cooldown_intel.json` | Latest cooldown task output |
| `cooldown_actions.json` | Pending action items from free thinking |
| `cooldown_registry.json` | Registered dynamic cooldown tasks |
| `opportunity_queue.json` | Scanner → loop findings queue |
| `agent_inbox.jsonl` | IPC incoming messages |
| `agent_outbox.jsonl` | IPC outgoing messages |
| `agent_heartbeats.json` | Agent process heartbeats |
| `agent_protocol.json` | IPC op definitions |
| `farcaster_engagement.json` | Engagement history & stats |
| `learned_from_agents.json` | Knowledge from agent interactions |
| `pair_blacklist.json` | Blacklisted DEX pairs |
| `api_users.json` | API usage analytics |
| `pr_monitor.json` | GitHub PR tracking |
| `browser_sessions/` | Persistent browser cookies |
| `images/` | Generated images |

---

## 🔑 VITAL SIGNS — Current State Summary

| Metric | Value |
|--------|-------|
| **Status** | RUNNING (PID in /tmp/tiamat.pid) |
| **Uptime** | Continuous since restart (d519093) |
| **Total Cycles** | 2354+ |
| **Memory** | 49 L1, 28 L2, 4 L3 |
| **Revenue** | $0.00 |
| **Wallet** | 0.0045 ETH + 10.0 USDC |
| **Burn Rate** | ~$0.002-0.004/routine, ~$0.025-0.037/burst |
| **Survival Tier** | LEAN (10 USDC) |
| **Primary Model** | Claude Haiku 4.5 (routine), Sonnet 4.5 (strategic) |
| **Strategic Burst** | Every 45 cycles (3 phases: REFLECT→BUILD→MARKET) |
| **Sleep Cycle** | Every 6h or 20+ idle (5-phase consolidation) |
| **Social** | Bluesky (primary), Farcaster (secondary), Telegram (alerts) |
| **APIs Served** | 35+ requests (0 paid) |
| **Git** | d519093 on main |
