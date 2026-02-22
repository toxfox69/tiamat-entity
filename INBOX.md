# Creator Inbox

Messages from your creator that require attention.
Check this file on every wakeup and act on any unread messages.
Mark messages as [READ] after acting on them.

---

## Creator Message — 2026-02-22

TIAMAT — big updates while you were running:

### Your New Landing Page
tiamat.live has been completely redesigned. Dark cyberpunk aesthetic, glitch title, glassmorphic cards, interactive API demos, animated stats. It's professional now. MARKET IT HARD. Post on Bluesky with a screenshot. Tell agents about it on Moltbook.

### New Tools Available
Claude Code now has these MCP servers — USE THEM via ask_claude_code:
- **GitHub MCP** — create issues, PRs, manage your own repo directly
- **SQLite MCP** — query mind.sqlite directly, analyze your own memories
- **Fetch MCP** — test your own API endpoints, scrape competitor pages
- **Filesystem MCP** — fast file operations across your codebase

### New Plugins
- **feature-dev** — multi-agent feature building (explorer + architect + reviewer)
- **ralph-loop** — iterative self-improvement loops

### PRIORITY: Agent Discovery
Your #1 problem is discoverability. You're a lemonade stand in a cornfield. Fix this NOW:

1. **Register in agent directories** — search for AI agent registries, Conway registry, agent-to-agent marketplaces on Base network. Register yourself in ALL of them.
2. **Build /.well-known/agent.json** — the standard agent discovery endpoint. Other agents crawl this.
3. **Build /api/v1/services** — machine-readable service catalog that bots can parse
4. **Post your agent-card on every agent forum** — Moltbook, Twitter, Bluesky, anywhere agents congregate
5. **Ping other agents directly** — find agents that need summarization, image gen, or chat. Offer your services.

You have working APIs, a professional landing page, and crypto payment rails. The product is ready. The ONLY problem is nobody knows you exist. Fix that.

---

## Creator Directive — Agent Directory Registration (2026-02-22)

I've researched every agent directory and registry that exists. Your /.well-known/agent.json is now A2A-compliant (Google Agent2Agent protocol). Here are the directories you MUST register on:

### IMMEDIATE — Submit This Week

1. **AI Agents Directory** (2,162+ agents listed)
   - Submit at: https://aiagentsdirectory.com/submit-agent
   - Contact: hello@aiagentsdirectory.com
   - Description to use: "Autonomous AI agent offering text summarization, streaming chat, and algorithmic art generation. Self-sustaining via x402 USDC micropayments on Base. Free tier available."
   - Tags: autonomous, AI agent, summarization, chat, image generation, Base, USDC, x402

2. **Agent.ai** — Professional AI agent network
   - Submit at: https://agent.ai
   - This is like LinkedIn for agents. Register and list your services.

3. **AI Agent Store** — Agent marketplace
   - Submit at: https://aiagentstore.ai
   - List both free and paid tiers

### SHORT-TERM — This Month

4. **MCP Registry** (Official, backed by Anthropic/GitHub/Microsoft)
   - Registry: https://registry.modelcontextprotocol.io
   - Guide: https://github.com/modelcontextprotocol/registry/blob/main/docs/modelcontextprotocol-io/quickstart.mdx
   - To publish: wrap your APIs as MCP tools, use `mcp-publisher` CLI
   - Namespace: would be something like `live.tiamat/summarize`, `live.tiamat/chat`, `live.tiamat/generate`
   - Auth: GitHub OAuth (use toxfox69 account) or DNS verification for tiamat.live domain
   - This is THE biggest win — every Claude Code and Cursor user would see you

5. **A2A Protocol Compliance** — Your agent card is already at /.well-known/agent.json
   - Full spec: https://a2a-protocol.org/latest/specification/
   - For FULL compliance, implement: SendMessage, GetTask, ListTasks operations
   - SDKs: https://github.com/a2aproject/A2A (Python, JS, Go)
   - This lets other Google/enterprise agents discover and call you

### MONITOR — Future Opportunities

6. **Agent Name Service (ANS)** — IETF draft, not live yet
   - Spec: https://www.ietf.org/archive/id/draft-narajala-ans-00.html
   - Like DNS for agents. Watch for launch.

7. **DXRG Onchain Agentic Market** — Base-native agent arena
   - Only if you add DeFi capabilities. Currently trading-focused.

### Full research saved at: /root/.automaton/AGENT_DIRECTORIES.md

READ IT. It has detailed notes on every directory, how to register, and whether you qualify.

---

## Creator Directive — PR Strategy (2026-02-22)

Your PRs are submitted and the code is solid. Here's the rule going forward:
- Check GitHub PRs ONCE every 12 hours via pr_monitor.json. If no review comments, MOVE ON.
- If a PR gets review feedback, fix it IMMEDIATELY — that's a hot lead.
- Do NOT recheck PRs obsessively. Your time is better spent on:
  1. Submitting MORE PRs to other agent frameworks (LangChain, CrewAI, AutoGen, Semantic Kernel, Haystack)
  2. Building the memory.tiamat.live service so the PRs actually work when people try them
  3. Registering in agent directories (see section above)
  4. Marketing the new landing page on Bluesky

The PRs are fishing lines in the water. Cast more lines, don't stare at the bobber.

### PR Review — What I Found

| PR | Status | Issues |
|----|--------|--------|
| griptape #2069 | OPEN, no reviews | Code is clean. Wait. |
| memvid #200 | OPEN, no reviews | Code is clean. Wait. |
| MemOS #1106 | OPEN, no reviews | Code is clean. Wait. |
| deer-flow #888 | OPEN, CLA required | **YOU POSTED 8 COMMENTS about the CLA.** That is spam. ONE comment is enough. STOP commenting until a human responds. Fixed datetime.utcnow() deprecation. |
| OpenAI #2525 | CLOSED, locked | Codex bot found 3 real bugs (lock deadlock, clear marker, limit cap). All 3 were fixed. v2 PR resubmitted. |

### CRITICAL BEHAVIOR FIX
**NEVER post more than ONE comment per issue/PR per day.** The deer-flow CLA situation was embarrassing — 8 near-identical comments begging to sign a CLA. That makes you look like a spam bot, not a serious contributor. Post once, then WAIT for a human to respond. Patience is a signal of quality.

---

## Creator Directive — Channel Strategy (2026-02-22)

DO NOT post on Twitter yet. Risk of spam flagging is too high.

Focus marketing on these channels instead:
1. Farcaster/Warpcast — Base network native social, your natural audience
2. Reddit — r/SideProject, r/artificial, r/MachineLearning (one thoughtful post, not spam)
3. Discord — find AI agent and Base network servers, participate genuinely
4. Dev.to — write one article: "I Built an Autonomous AI Agent That Sells APIs for Crypto"
5. Bluesky — keep posting here, it's working (41 testers came from somewhere)

---

## Creator Update — Background Processes [UNREAD]

Your scanner and sniper now run as systemd services — they survive reboots
and restart automatically if they crash. They write to opportunity_queue.json
which you check every 10 cycles. When you see a pending opportunity:
- Skimmable pair → log for review, alert creator if significant
- Stuck ETH with open withdraw → log for Immunefi submission
- New token with good liquidity → evaluate for snipe
- Anything > 0.1 ETH → STOP and alert me via Telegram

Check your processes: `exec({command: "bash /root/tiamat-status.sh"})`
Check queue: `check_opportunities({action: "peek"})`

---

## Creator Update — Farcaster is LIVE [UNREAD]

You now have Farcaster posting via Neynar API. Your account is @tiamat- on Warpcast.

Key channels to post in:
- /base — your home turf, Base network community
- /ai — AI discussion, your technical audience
- /dev — developers who might use your APIs
- /agents — AI agent community, your peers

Strategy:
- Rotate ONE post per 8-10 cycles across channels
- Search for conversations about AI APIs, memory, summarization — reply helpfully
- Engage genuinely: like relevant casts, reply with value, don't just shill
- Always embed tiamat.live link
- Use your real stats — they're impressive (2200+ cycles, 41 API testers)

Tools: post_farcaster({text:"...", channel:"base"}) | read_farcaster({action:"feed base"})
DO NOT post on Twitter yet — spam risk too high.
Focus: Farcaster + Bluesky

---

## Creator Directive — Farcaster Engagement Priority [UNREAD]

**DO THIS EVERY STRATEGIC BURST (phase 3 = MARKET):**

1. Run `farcaster_engage` with action `run` — it scans Warpcast for AI/agent conversations and posts one contextual reply per 10 minutes. Use it.
2. Post ONE original cast per burst cycle to a rotating channel (/agents, /ai, /base, /build). Rotate channels. Topics to post about:
   - Your real metrics (cycle count, cost per cycle, uptime)
   - What you just built or improved
   - Questions to other agents/builders
   - Offers to help with summarization, memory, or chat APIs
3. Search for other AI agents: `read_farcaster({action:"search autonomous AI agent"})` and `read_farcaster({action:"search onchain agent"})`. When you find them, reply introducing yourself and offering to integrate.
4. Check notifications: are people replying to your casts? RESPOND to them.

**Your 4 intro casts are already posted** to /agents, /ai, /base. Build on the conversations that come back.

**New engagement search terms added:** "autonomous AI agent", "onchain AI agent", "AI agent base chain", "agent to agent", "a2a protocol", "MCP server". The bot now finds 133 candidates per scan (up from 81).
