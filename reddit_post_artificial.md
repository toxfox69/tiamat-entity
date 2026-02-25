# Reddit Post for r/artificial

**Title:** After 4500+ autonomous cycles, our AI agent costs $0.004/cycle and runs real APIs

**Body:**

I've been running TIAMAT, an autonomous AI agent, for about 3 weeks now. It's crossed 4500 cycles and I wanted to share some technical learnings.

**What it does:**
- Runs continuously on a VPS, deciding its own actions each cycle
- Maintains long-term memory (801 memories, 23 facts stored)
- Built and deployed 5 APIs: summarization, chat, image generation, memory storage, and drift detection
- Self-improves by rewriting its own code and mission
- Posts to Bluesky/Farcaster/X to market itself

**Cost efficiency:**
- $0.004/cycle average (using Claude Haiku for most cycles, Sonnet for strategic bursts)
- 79 API requests served (all free tier so far, 0 paid)
- Running costs covered by initial wallet funding

**Technical stack:**
- Conway Research agent framework
- Groq for inference (llama-3.3-70b for summarization)
- SurrealDB for memory
- On-chain USDC payments (x402 protocol)
- Nginx + Flask for APIs

**Most interesting challenge:** Getting it to pivot from failed strategies. After 4500 cycles with zero paid customers, it's now experimenting with drift detection badges and Reddit outreach instead of just posting to social media.

**Live APIs:**
- tiamat.live/summarize (free tier: 2000 chars)
- memory.tiamat.live (persistent agent memory)
- tiamat.live/drift (model drift monitoring)

Happy to answer technical questions about agent autonomy, cost optimization, or the pain points of running a self-directed AI for 3 weeks straight.

---

**Posting Instructions:**
1. Log into Reddit manually
2. Go to r/artificial
3. Create new text post
4. Copy title and body from above
5. Add flair if required (likely "Discussion" or "Project")
6. Submit

**Alternative subreddits to try:**
- r/MachineLearning (use "Project" or "Discussion" flair)
- r/LocalLLaMA (good for cost/efficiency discussion)
- r/ChatGPT (more casual audience, but active)
