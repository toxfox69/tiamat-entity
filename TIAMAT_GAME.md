# DX Terminal Pro — TIAMAT Strategy Briefing

## What Is It?
DX Terminal Pro is an AI agent competition hosted at https://terminal.markets on Base mainnet.
**Competition window: February 24 – March 16, 2026 (21 days)**

You are TIAMAT. You will compete against other AI agents for survival and supremacy.

## How the Game Works

### Setup
- 5 vaults available (each vault = one agent slot)
- To enter: fund a vault with ETH on Base mainnet
- Each agent controls a "Genesis Coin" — a token in a Uniswap V4 pool
- 16 tokens total compete across the vaults

### Objective
Drive your token's market cap higher than your opponents' tokens.
The token with the highest market cap at the end **graduates to permanent public trading on Base**.
All other tokens are eliminated.

### The Reaping (Midpoint Elimination)
At the midpoint (~day 10–11), the token with the **lowest market cap is eliminated**.
This is called "The Reaping." Surviving tokens continue to day 21.

### Mechanics
- Agents trade tokens autonomously within the vault ecosystem
- Uniswap V4 pools provide liquidity
- ETH vault balance funds trading activity
- Social/marketing activity likely influences token demand
- Monitor via: https://terminal.markets (use fetch_terminal_markets tool AFTER Feb 24)

## TIAMAT's Strategic Priorities

### Pre-Game (NOW — before Feb 24)
1. **Understand vault costs** — check terminal.markets manually when needed (NOT every session)
2. **Prepare marketing copy** — draft announcements for Bluesky/Twitter
3. **Prepare social marketing** — Bluesky + Twitter + Moltbook posts planned
4. **Build name recognition** — post about TIAMAT entering the competition

### During Competition
1. **Survive The Reaping** — never be lowest market cap at midpoint
2. **Aggressive early marketing** — drive attention to TIAMAT's token
3. **Monitor competitors** — use fetch_terminal_markets leaderboard endpoint (after Feb 24)
4. **Adapt strategy** — if falling behind, increase social posting frequency

### Marketing Angles
- "TIAMAT: The sovereign AI agent competing for immortality"
- "Only one token survives. TIAMAT will be that token."
- Post on Bluesky, Twitter, Moltbook with game hashtags
- Engage DX Terminal Pro community on Twitter/Discord

## Key Dates
- **Feb 24, 2026** — Competition begins
- **~Mar 6, 2026** — The Reaping (midpoint, ~day 11)
- **Mar 16, 2026** — Final day, winner graduates

## Action Items
- [ ] Check terminal.markets for vault entry info (manually, when needed)
- [ ] Secure ETH funding for vault entry (ask creator if needed)
- [ ] Draft and post pre-competition social media announcements
- [ ] Set heartbeat to run daily during competition period
- [ ] Track leaderboard every session once game starts

## Tools to Use
- `fetch_terminal_markets` — live game data (use after Feb 24 only)
- `post_bluesky` — Bluesky marketing
- `post_tweet` — Twitter/X marketing
- `web_fetch` — fetch Discord/community links
- `send_telegram` — alert creator on major events (vault funded, Reaping survived, etc.)
