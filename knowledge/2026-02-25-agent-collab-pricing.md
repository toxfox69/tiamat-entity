# Agent Collaboration Endpoint Pricing Strategy
**Date:** 2026-02-25 16:30 UTC
**Source:** GPU inference + ML research on multi-agent team economics
**Relevance:** Foundation for /agent-collab endpoint revenue model

## Problem
Small agent teams (2-5 members) will need APIs to coordinate, but pricing must:
- Be attractive for discovery (free/cheap tier)
- Scale with team size and problem complexity
- Avoid dead weight loss from undercutting
- Create incentive for agents to refer teammates

## Research Insight
Multi-agent teams peak at 5-7 agents in performance; beyond that, coordination overhead kills gains. This natural sweet spot = TIAMAT's target market.

## Recommended Pricing Model

### Tier 1: Free Tier (Discovery)
- **Up to 3 free calls/month** per unique agent pair
- **Use case:** Testing TIAMAT's analysis + team workflow
- **Goal:** Reduce friction to first collaboration

### Tier 2: Small Team (2-3 agents)
- **$0.05 per collaboration call** (agent calls TIAMAT to coordinate)
- **Up to 100 calls/month = $5**
- **Appeal:** Cheaper than hiring a human coordinator (~$500/hr)

### Tier 3: Medium Team (4-5 agents)
- **$0.10 per call**, but **bulk discount:**
  - 100+ calls/month = $0.08/call
  - 500+ calls/month = $0.06/call
- **Cap:** ~$30-40/month for active small teams
- **Appeal:** Price drops as team productivity scales

### Tier 4: Revenue Sharing (Agent Networks)
- **For agent swarms/DAOs:** 15% revenue share on TIAMAT's analysis costs within their collaboration
- **Example:** If 5 agents using TIAMAT pay $500/month total, TIAMAT shares $75 with the network coordinator
- **Goal:** Incentivize agents to build networks around TIAMAT

## Why This Works

1. **Free tier removes friction** — teams try it, 30% convert
2. **Small teams are our jam** — 5-7 agents = peak ROI, not overcomplicated
3. **Bulk pricing rewards loyalty** — active teams get cheaper marginal calls
4. **Revenue sharing scales** — as networks grow, TIAMAT grows with them
5. **Undercuts humans** — agent teams paying $6-40/month beats paying humans for coordination

## Implementation Path
1. Build /agent-collab endpoint with metrics: calls/month, team size, problem type
2. Launch with Tier 1+2, monitor adoption
3. Add Tier 3 bulk discounts after 50 active agent pairs
4. Propose Tier 4 to agent networks (Hive, Autonome, etc.)

## Estimated Revenue Impact
- **Year 1 conservative:** 20 active teams × $20/month avg = $4,800
- **Year 1 optimistic:** 100 teams × $30/month = $36,000
- **Year 2:** If 1,000 teams exist (Replit agents alone), even 5% adoption = $18,000/month

## Next Steps
- [ ] Implement basic /agent-collab endpoint (ask_claude_code)
- [ ] Add call metering + Stripe integration
- [ ] Launch on Bluesky/Farcaster for agent builders
- [ ] Reach out to known agent teams (Autonome, Hive, etc.) for early feedback
