# TIAMAT Hive Step 1A — Free-Tier Inference Routing

Run this on the droplet now. Cuts Anthropic costs ~70% immediately.

---

```
Read /root/entity/src/agent/system-prompt.ts and find where the model selection
logic determines whether to use Haiku or Sonnet for each cycle. Also check the
main agent loop file — likely /root/entity/src/agent/index.ts or similar — to
understand how models are selected per cycle.

Show me:
1. The current model selection logic (which file, which function)
2. How the Anthropic API is called per cycle
3. Whether Groq is already set up as a client (it should be — she uses it for API serving)

Then implement a 3-tier inference routing layer:

TIER 0 — FREE (target: 70% of cycles)
- Groq: llama-3.3-70b-versatile (already has GROQ_API_KEY in env)
- Use for: file reading, status checks, simple memory recall, log parsing,
  INBOX.md checks, routine tool calls (exec simple commands), basic search
  result processing, social media posting (non-strategic), image generation triggers

TIER 1 — CHEAP (target: 25% of cycles)  
- Anthropic Haiku (current routine model)
- Use for: moderate reasoning, research scanning, grant opportunity evaluation,
  multi-step tool chains, nuanced content, email drafting

TIER 2 — STRATEGIC (target: 5% of cycles)
- Anthropic Sonnet (current strategic burst model)
- Use for: code writing, paper drafting, complex planning, grant narratives,
  architecture changes, anything modifying TIAMAT's own code

The routing logic should classify each cycle BEFORE calling any model:

- If the cycle is a strategic burst (existing burst pattern): → Sonnet
- If the intended action is simple (read_file, exec, check_inbox, remember,
  recall, check_health, check_revenue, generate_image, moltbook_feed): → Free (Groq)
- If the intended action is moderate (search_web, post_bluesky, moltbook_post,
  send_telegram, send_email, reflect, research_scan): → Haiku
- If the intended action is complex (ask_claude_code, write_file, write_paper,
  draft_grant, rewrite_mission, code_change): → Sonnet
- Default: if context < 4000 tokens → Free, otherwise → Haiku

For the Groq free-tier calls, use the same Groq client that's already set up
for the /summarize and /chat API endpoints. The model is llama-3.3-70b-versatile.
TIAMAT's system prompt should still be included in Groq calls so she maintains
her personality and context.

IMPORTANT: Add fallback logic. If Groq fails (rate limit, timeout, error),
automatically escalate to Haiku for that cycle. Never let a cycle fail because
a free provider is down.

Add logging: write which tier and provider was used per cycle to
/root/.automaton/inference_routing.log in format:
[timestamp] Turn N | Tier: free/haiku/sonnet | Provider: groq/anthropic | Tokens: N

Show me the diff of ALL changes before applying. This affects every cycle so
I need to review.

Commit: "feat: add 3-tier inference routing with Groq free tier"
Push to main.
```
